"""Give a unit cost to zero-cost stock - and to what was already delivered / consumed from it.

Per item and new unit cost:
1. every incoming move that came in at 0 gets value = qty x cost (Odoo's own manual-value record,
   so FIFO / average and the item's cost follow) -> stock on hand is revalued;
2. deliveries / consumption that FIFO recorded as taken from those batches get the batch's new
   cost (exact per batch);
3. optionally, deliveries / consumption made at 0 with no batch record (before FIFO) get qty x cost.
Real-time valued items get a journal entry for each change, on Odoo's own accounts for that move.
Everything is logged in Cost Revaluations."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CostRevalueWizard(models.TransientModel):
    _name = 'combine.cost.revalue'
    _description = 'Revalue zero-cost stock'

    company_id = fields.Many2one('res.company', default=lambda s: s.env.company, required=True)
    categ_ids = fields.Many2many('product.category', 'combine_revalue_categ_rel', 'wizard_id', 'categ_id',
                                 string='Item Categories', help='Used by "Load zero-cost items". Empty = all.')
    product_ids = fields.Many2many('product.product', 'combine_revalue_product_rel', 'wizard_id', 'product_id',
                                   string='Items', help='Used by "Load zero-cost items". Empty = all.')
    line_ids = fields.One2many('combine.cost.revalue.line', 'wizard_id', string='Items to revalue')
    do_batch = fields.Boolean(string='Re-cost deliveries / consumption taken from these batches (FIFO record)', default=True)
    do_flat = fields.Boolean(string='Re-cost other deliveries / consumption made at 0 (no batch record)', default=True,
                             help='Deliveries and consumption made before FIFO (or of non-FIFO items) at cost 0: '
                                  'valued at quantity x the new unit cost.')
    flat_date_from = fields.Date(string='... made on or after', help='Empty = all dates.')
    accounting_date = fields.Date(string='Accounting date', default=fields.Date.context_today, required=True,
                                  help='Date of the journal entries for real-time valued items.')
    note = fields.Char(string='Reason')
    counterpart_account_id = fields.Many2one(
        'account.account', string='Counterpart account (credit)',
        help='Real-time valued items only: credited with the total value given to the zero-cost stock '
             '(e.g. opening stock / inventory adjustment account). Empty = no journal entry.')
    consumption_account_id = fields.Many2one(
        'account.account', string='Consumption account (debit)',
        help='Real-time valued items only: debited with the cost given to what was already consumed / '
             'delivered at 0. The rest (still on hand) is debited to the item category\'s stock account.')
    has_real_time = fields.Boolean(compute='_compute_has_real_time')

    @api.depends('line_ids.product_id')
    def _compute_has_real_time(self):
        for wiz in self:
            wiz.has_real_time = any(p.valuation == 'real_time' for p in wiz.line_ids.product_id)

    def _zero_in_moves(self, product):
        return self.env['stock.move'].sudo().search([
            ('product_id', '=', product.id), ('company_id', '=', self.company_id.id), ('state', '=', 'done'),
            ('is_in', '=', True), ('value', '=', 0), ('quantity', '>', 0)], order='date, id')

    def _zero_batch_allocs(self, in_moves):
        return self.env['combine.fifo.allocation'].sudo().search([
            ('in_move_id', 'in', in_moves.ids), ('value', '=', 0), ('quantity', '>', 0)])

    def _zero_flat_outs(self, product):
        domain = [('product_id', '=', product.id), ('company_id', '=', self.company_id.id), ('state', '=', 'done'),
                  ('is_out', '=', True), ('value', '=', 0), ('quantity', '>', 0), ('x_fifo_allocation_ids', '=', False)]
        if self.flat_date_from:
            domain.append(('date', '>=', fields.Datetime.to_datetime(self.flat_date_from)))
        return self.env['stock.move'].sudo().search(domain, order='date, id')

    def _reopen(self):
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'new', 'name': _('Revalue zero-cost stock')}

    def action_load(self):
        """Fill the list with every item that has stock received at 0 (or out at 0)."""
        self.ensure_one()
        Move = self.env['stock.move'].sudo()
        base = [('company_id', '=', self.company_id.id), ('state', '=', 'done'), ('value', '=', 0), ('quantity', '>', 0)]
        if self.product_ids:
            base.append(('product_id', 'in', self.product_ids.ids))
        if self.categ_ids:
            base.append(('product_id.categ_id', 'child_of', self.categ_ids.ids))
        products = Move.search(base + ['|', ('is_in', '=', True), ('is_out', '=', True)]).product_id
        existing = self.line_ids.product_id
        self.line_ids = [(0, 0, {'product_id': p.id, 'new_cost': p.x_production_cost or 0.0})
                         for p in products.sorted('display_name') if p not in existing]
        return self._reopen()

    def action_preview(self):
        self.ensure_one()
        self.line_ids._compute_preview()
        return self._reopen()

    def action_apply(self):
        self.ensure_one()
        if not self.env.user.has_group('account.group_account_manager'):
            raise UserError(_('Only accounting managers can revalue stock.'))
        lines = self.line_ids.filtered(lambda l: l.new_cost > 0)
        if not lines:
            raise UserError(_('Enter a new unit cost (above 0) on at least one item.'))
        if self.has_real_time and bool(self.counterpart_account_id) != bool(self.consumption_account_id):
            raise UserError(_('For real-time valued items set both the counterpart and the consumption account '
                              '(or neither, for no journal entry).'))
        reval = self.env['combine.cost.revaluation'].create({
            'company_id': self.company_id.id, 'accounting_date': self.accounting_date, 'note': self.note})
        RMove = self.env['combine.cost.revaluation.move']
        PV = self.env['product.value'].sudo()
        manual_entry = {}   # stock valuation account -> [received value, consumed value] (real-time items, no Odoo entry)
        for line in lines:
            product, cost = line.product_id.with_company(self.company_id), line.new_cost
            stock_delta = cons_delta = stock_qty = cons_qty = 0.0
            no_odoo_entry_in = no_odoo_entry_out = 0.0
            # 1. stock received at 0
            ins = self._zero_in_moves(product)
            if product.cost_method == 'standard':
                # standard cost: the value of all stock follows the item cost
                product.sudo().standard_price = cost
            for move in ins:
                qty = move._get_valued_qty()
                new = self.company_id.currency_id.round(qty * cost)
                PV.create({'move_id': move.id, 'value': new, 'description': _('%(r)s: unit cost %(c)s', r=reval.name, c=cost)})
                entry = move._combine_post_value_delta(new, self.accounting_date, reval.name)
                if not entry and product.valuation == 'real_time':
                    no_odoo_entry_in += move.value
                RMove.create({'revaluation_id': reval.id, 'product_id': product.id, 'stock_move_id': move.id,
                              'reference': move.picking_id.name or move.reference, 'kind': 'stock_in', 'quantity': qty,
                              'old_value': 0.0, 'new_value': move.value, 'delta': move.value, 'account_move_id': entry.id})
                stock_delta += move.value
                stock_qty += qty
            # 2. deliveries / consumption FIFO took from those batches
            if self.do_batch and ins:
                for alloc in self._zero_batch_allocs(ins):
                    add = self.company_id.currency_id.round(alloc.quantity * cost)
                    out = alloc.out_move_id
                    old = out.value
                    alloc.write({'value': add, 'unit_cost': cost})
                    out.sudo().value = old + add
                    entry = out._combine_post_value_delta(add, self.accounting_date, reval.name)
                    if not entry and product.valuation == 'real_time':
                        no_odoo_entry_out += add
                    RMove.create({'revaluation_id': reval.id, 'product_id': product.id, 'stock_move_id': out.id,
                                  'reference': out.picking_id.name or out.reference, 'kind': 'consumption_batch',
                                  'quantity': alloc.quantity, 'old_value': old, 'new_value': out.value, 'delta': add,
                                  'account_move_id': entry.id})
                    cons_delta += add
                    cons_qty += alloc.quantity
            # 3. other deliveries / consumption made at 0
            if self.do_flat:
                for out in self._zero_flat_outs(product):
                    qty = out._get_valued_qty()
                    add = self.company_id.currency_id.round(qty * cost)
                    out.sudo().value = add
                    entry = out._combine_post_value_delta(add, self.accounting_date, reval.name)
                    if not entry and product.valuation == 'real_time':
                        no_odoo_entry_out += add
                    RMove.create({'revaluation_id': reval.id, 'product_id': product.id, 'stock_move_id': out.id,
                                  'reference': out.picking_id.name or out.reference, 'kind': 'consumption_flat',
                                  'quantity': qty, 'old_value': 0.0, 'new_value': add, 'delta': add,
                                  'account_move_id': entry.id})
                    cons_delta += add
                    cons_qty += qty
            product._update_standard_price()
            self.env['combine.cost.revaluation.line'].create({
                'revaluation_id': reval.id, 'product_id': product.id, 'new_cost': cost, 'stock_qty': stock_qty,
                'consumed_qty': cons_qty, 'stock_delta': stock_delta, 'consumption_delta': cons_delta})
            if no_odoo_entry_in or no_odoo_entry_out:
                acc = product._get_product_accounts()['stock_valuation']
                agg = manual_entry.setdefault(acc, [0.0, 0.0])
                agg[0] += no_odoo_entry_in
                agg[1] += no_odoo_entry_out
        if manual_entry and self.counterpart_account_id:
            reval.journal_entry_id = self._post_manual_entry(reval, manual_entry)
        return {'type': 'ir.actions.act_window', 'res_model': 'combine.cost.revaluation', 'res_id': reval.id,
                'view_mode': 'form', 'target': 'current', 'name': reval.name}


    def _post_manual_entry(self, reval, manual_entry):
        """Real-time items whose moves have no Odoo stock entry (locations without valuation account):
        Dr stock (still on hand) + Dr consumption (already consumed) / Cr counterpart (all of it)."""
        cur = self.company_id.currency_id
        lines, total = [], 0.0
        for acc, (received, consumed) in manual_entry.items():
            on_hand = cur.round(received - consumed)
            if not cur.is_zero(on_hand):
                lines.append((0, 0, {'account_id': acc.id, 'name': _('%s - stock on hand revalued', reval.name),
                                     'debit': max(on_hand, 0.0), 'credit': max(-on_hand, 0.0)}))
            if not cur.is_zero(consumed):
                lines.append((0, 0, {'account_id': self.consumption_account_id.id,
                                     'name': _('%s - consumption / deliveries re-costed', reval.name),
                                     'debit': cur.round(consumed), 'credit': 0.0}))
            total += received
        if cur.is_zero(total):
            return False
        lines.append((0, 0, {'account_id': self.counterpart_account_id.id, 'name': _('%s - zero-cost stock revalued', reval.name),
                             'debit': 0.0, 'credit': cur.round(total)}))
        journal = self.company_id.account_stock_journal_id or self.env['account.journal'].search(
            [('company_id', '=', self.company_id.id), ('type', '=', 'general')], limit=1)
        if not journal:
            raise UserError(_('Set a stock journal on the company (Inventory settings) to post the revaluation entry.'))
        entry = self.env['account.move'].sudo().create({
            'move_type': 'entry', 'journal_id': journal.id, 'date': self.accounting_date,
            'ref': '%s - %s' % (reval.name, self.note or _('zero-cost stock revaluation')), 'line_ids': lines})
        entry.action_post()
        return entry


class CostRevalueWizardLine(models.TransientModel):
    _name = 'combine.cost.revalue.line'
    _description = 'Revalue zero-cost stock - item'

    wizard_id = fields.Many2one('combine.cost.revalue', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True, string='Item')
    uom_id = fields.Many2one(related='product_id.uom_id')
    cost_method = fields.Selection(related='product_id.cost_method')
    valuation = fields.Selection(related='product_id.valuation', string='Accounting')
    new_cost = fields.Float(string='New Unit Cost', digits='Product Price')
    zero_in_qty = fields.Float(string='Received at 0', digits='Product Unit', readonly=True)
    zero_on_hand_qty = fields.Float(string='On hand at 0', digits='Product Unit', readonly=True)
    zero_batch_qty = fields.Float(string='Sold at 0 (batch)', digits='Product Unit', readonly=True)
    zero_flat_qty = fields.Float(string='Sold at 0 (no batch)', digits='Product Unit', readonly=True)
    stock_add = fields.Float(string='Stock value added', readonly=True)
    consumption_add = fields.Float(string='Consumption added', readonly=True)

    def _compute_preview(self):
        for line in self:
            wiz = line.wizard_id
            product = line.product_id.with_company(wiz.company_id)
            ins = wiz._zero_in_moves(product)
            in_qty = sum(m._get_valued_qty() for m in ins)
            on_hand = 0.0
            if product.cost_method == 'fifo':
                remaining = product._get_remaining_moves().get(product, {})
                on_hand = sum(q for m, q in remaining.items() if m in ins)
            elif not product.standard_price:
                on_hand = product.qty_available
            batch = sum(wiz._zero_batch_allocs(ins).mapped('quantity')) if wiz.do_batch and ins else 0.0
            flat = sum(m._get_valued_qty() for m in wiz._zero_flat_outs(product)) if wiz.do_flat else 0.0
            line.write({'zero_in_qty': in_qty, 'zero_on_hand_qty': on_hand, 'zero_batch_qty': batch, 'zero_flat_qty': flat,
                        'stock_add': in_qty * line.new_cost, 'consumption_add': (batch + flat) * line.new_cost})

    @api.onchange('new_cost')
    def _onchange_new_cost(self):
        for line in self:
            line.stock_add = line.zero_in_qty * line.new_cost
            line.consumption_add = (line.zero_batch_qty + line.zero_flat_qty) * line.new_cost
