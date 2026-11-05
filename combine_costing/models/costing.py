from collections import defaultdict

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero


# ============================================================ standard cost card
class CostCard(models.Model):
    """Standard cost of an item from a date. A purchased item (raw material,
    stores) has a standard price; a produced item (lap, sliver, roving, yarn)
    has a recipe - inputs per unit of output - plus a standard conversion cost
    per unit for its department. A new card from a later date replaces the
    old one from then on, so past periods keep their standard."""
    _name = 'combine.cost.card'
    _description = 'Standard Cost Card'
    _inherit = ['mail.thread']
    _order = 'product_id, date_from desc, id desc'
    _rec_name = 'product_id'

    product_id = fields.Many2one('product.product', string='Item', required=True, index=True, tracking=True)
    uom_id = fields.Many2one(related='product_id.uom_id', string='UoM')
    date_from = fields.Date(string='Effective From', required=True, default=fields.Date.context_today, tracking=True)
    kind = fields.Selection([('purchased', 'Purchased item - standard price'), ('produced', 'Produced item - recipe')],
                            required=True, default='purchased', tracking=True)
    department_id = fields.Many2one('combine.production.department', string='Produced In')
    std_price = fields.Float(string='Standard Price / Unit', digits=(16, 4), tracking=True)
    line_ids = fields.One2many('combine.cost.card.line', 'card_id', string='Inputs per Unit', copy=True)
    conversion_cost = fields.Float(string='Std. Conversion / Unit', digits=(16, 4), tracking=True,
                                   help='Power, wages, overheads of the department per unit of this output.')
    std_waste_pct = fields.Float(string='Std. Waste %', digits=(5, 2))
    material_cost = fields.Float(string='Std. Material / Unit', compute='_compute_cost', digits=(16, 4))
    std_cost = fields.Float(string='Standard Cost / Unit', compute='_compute_cost', digits=(16, 4))
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    active = fields.Boolean(default=True)
    note = fields.Char()

    @api.depends('kind', 'std_price', 'line_ids.qty', 'line_ids.product_id', 'conversion_cost', 'date_from')
    def _compute_cost(self):
        for card in self:
            if card.kind == 'purchased':
                card.material_cost = card.std_price
                card.std_cost = card.std_price
            else:
                material = sum(l.qty * self._std_cost(l.product_id, card.date_from, _depth=1) for l in card.line_ids)
                card.material_cost = material
                card.std_cost = material + card.conversion_cost

    @api.constrains('line_ids', 'product_id')
    def _check_recipe(self):
        for card in self:
            if card.line_ids.filtered(lambda l: l.product_id == card.product_id):
                raise ValidationError(_('%s cannot be an input of itself.', card.product_id.display_name))

    @api.model
    def _card_for(self, product, date=None):
        date = date or fields.Date.context_today(self)
        return self.search([('product_id', '=', product.id), ('date_from', '<=', date),
                            ('company_id', '=', self.env.company.id)], order='date_from desc, id desc', limit=1)

    @api.model
    def _std_cost(self, product, date=None, _depth=0):
        """Standard cost per unit (product UoM) of an item on a date; 0 if no card."""
        if _depth > 8:
            return 0.0
        card = self._card_for(product, date)
        if not card:
            return 0.0
        if card.kind == 'purchased':
            return card.std_price
        return sum(l.qty * self._std_cost(l.product_id, date or card.date_from, _depth + 1) for l in card.line_ids) + card.conversion_cost


class CostCardLine(models.Model):
    _name = 'combine.cost.card.line'
    _description = 'Standard Cost Card Input'

    card_id = fields.Many2one('combine.cost.card', required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one('product.product', string='Input Item', required=True)
    uom_id = fields.Many2one(related='product_id.uom_id', string='UoM')
    qty = fields.Float(string='Qty per Unit of Output', digits=(16, 6), required=True, default=1.0)
    std_price = fields.Float(string='Std. Price', compute='_compute_std', digits=(16, 4))
    std_value = fields.Float(string='Std. Value / Unit', compute='_compute_std', digits=(16, 4))

    @api.depends('product_id', 'qty', 'card_id.date_from')
    def _compute_std(self):
        Card = self.env['combine.cost.card']
        for line in self:
            line.std_price = Card._std_cost(line.product_id, line.card_id.date_from, _depth=1) if line.product_id else 0.0
            line.std_value = line.std_price * line.qty


# ============================================================ departments
class ProductionDepartment(models.Model):
    _inherit = 'combine.production.department'

    analytic_account_id = fields.Many2one('account.analytic.account', string='Cost Centre (Analytic)',
                                          help='Tag power, wages and overhead bills / vouchers with this cost centre; '
                                               'the month-end cost close takes the department\'s actual conversion cost from it.')
    next_department_id = fields.Many2one('combine.production.department', string='Next Department')


# ============================================================ department stock ledger
class DepartmentLedger(models.Model):
    """What each department holds: received from the store, received from the
    previous department, consumed, produced, transferred on, wasted. Its
    balance is the department's material + work in process."""
    _name = 'combine.dept.ledger'
    _description = 'Department Stock Ledger'
    _order = 'date, id'

    date = fields.Date(required=True, index=True)
    department_id = fields.Many2one('combine.production.department', required=True, index=True, ondelete='restrict')
    product_id = fields.Many2one('product.product', string='Item', required=True, index=True)
    qty = fields.Float(digits='Product Unit', help='Positive in, negative out (product UoM).')
    value = fields.Float(digits=(16, 2))
    kind = fields.Selection([
        ('issue', 'Issued from Store'), ('return', 'Returned to Store'),
        ('transfer_in', 'Received from Department'), ('consume', 'Consumed in Batch'),
        ('produce', 'Produced'), ('transfer_out', 'Transferred to Next Department'),
        ('to_store', 'Transferred to Store'), ('waste', 'Waste'), ('adjust', 'Count Adjustment'),
    ], required=True, index=True)
    batch_id = fields.Many2one('combine.production.batch', ondelete='cascade', index=True)
    issue_id = fields.Many2one('combine.material.issue', ondelete='cascade', index=True)
    count_id = fields.Many2one('combine.wip.count', ondelete='cascade', index=True)
    other_department_id = fields.Many2one('combine.production.department', string='From / To Department')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)

    @api.model
    def _balance(self, department, product, date=None, exclude_batch=None):
        dom = [('department_id', '=', department.id), ('product_id', '=', product.id)]
        if date:
            dom.append(('date', '<=', date))
        if exclude_batch:
            dom.append(('batch_id', '!=', exclude_batch.id))
        rows = self._read_group(dom, aggregates=['qty:sum', 'value:sum'])
        qty, value = rows[0] if rows else (0.0, 0.0)
        return qty or 0.0, value or 0.0


class MaterialIssue(models.Model):
    _inherit = 'combine.material.issue'

    def action_issue(self):
        res = super().action_issue()
        Ledger = self.env['combine.dept.ledger'].sudo()
        for issue in self.filtered(lambda i: i.state == 'done' and not Ledger.search_count([('issue_id', '=', i.id)])):
            Ledger.create([{
                'date': issue.date, 'department_id': issue.department_id.id, 'product_id': line.product_id.id,
                'qty': line.uom_id._compute_quantity(line.qty, line.product_id.uom_id), 'value': line.value,
                'kind': 'issue', 'issue_id': issue.id, 'company_id': issue.company_id.id,
            } for line in issue.line_ids if line.qty > 0])
        return res


# ============================================================ production batch
class ProductionBatch(models.Model):
    """One run / lot in one department: what went in (from its own stock -
    issued by the store or received from the previous department), what came
    out, the waste, and where the output went. Cost: actual material +
    conversion; standard from the cost card; the difference is the
    variance."""
    _name = 'combine.production.batch'
    _description = 'Production Batch'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'combine.stores.print.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(string='Batch No.', default=lambda self: _('New'), readonly=True, copy=False)
    lot_no = fields.Char(string='Lot / Batch Ref.', tracking=True)
    date = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    department_id = fields.Many2one('combine.production.department', required=True, tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    state = fields.Selection([('draft', 'Draft'), ('done', 'Completed'), ('cancel', 'Cancelled')],
                             default='draft', required=True, tracking=True, copy=False)
    shift = fields.Char()
    product_id = fields.Many2one('product.product', string='Output Item', required=True, tracking=True)
    uom_id = fields.Many2one(related='product_id.uom_id', string='UoM')
    qty_produced = fields.Float(string='Good Output', digits='Product Unit', tracking=True)
    qty_waste = fields.Float(string='Waste', digits='Product Unit', tracking=True)
    waste_product_id = fields.Many2one('product.product', string='Waste Item',
                                       help='Optional: saleable waste goes to the department stock as this item, at no cost.')
    destination = fields.Selection([('next', 'Next department'), ('store', 'Store (finished goods)'), ('stay', 'Stays in this department')],
                                   required=True, default='next', tracking=True)
    next_department_id = fields.Many2one('combine.production.department', string='Transfer To',
                                         compute='_compute_next', store=True, readonly=False, precompute=True)
    store_location_id = fields.Many2one('stock.location', string='Receive Into', domain="[('usage', '=', 'internal')]",
                                        compute='_compute_store_location', store=True, readonly=False, precompute=True)
    input_ids = fields.One2many('combine.production.batch.input', 'batch_id', string='Inputs', copy=True)
    stock_move_id = fields.Many2one('stock.move', string='Store Receipt', readonly=True, copy=False)
    card_id = fields.Many2one('combine.cost.card', string='Cost Card', readonly=True, copy=False)
    note = fields.Text()

    # costs (frozen at completion; conversion actual set by the month close)
    material_cost = fields.Monetary(string='Actual Material', readonly=True, copy=False)
    conversion_std = fields.Monetary(string='Std. Conversion', readonly=True, copy=False)
    conversion_actual = fields.Monetary(string='Actual Conversion', readonly=True, copy=False,
                                        help='Allocated by the month-end cost close; until then equal to standard.')
    transfer_value = fields.Monetary(string='Transfer Value', readonly=True, copy=False,
                                     help='Actual material + standard conversion: the value passed to the next department / store.')
    actual_cost = fields.Monetary(string='Actual Cost', compute='_compute_costs', store=True)
    std_material = fields.Monetary(string='Std. Material (for output)', readonly=True, copy=False)
    std_cost = fields.Monetary(string='Standard Cost', compute='_compute_costs', store=True)
    variance = fields.Monetary(string='Total Variance', compute='_compute_costs', store=True,
                               help='Actual - standard; positive = adverse (cost more than standard).')
    actual_unit_cost = fields.Float(string='Actual / Unit', compute='_compute_costs', store=True, digits=(16, 4))
    std_unit_cost = fields.Float(string='Standard / Unit', compute='_compute_costs', store=True, digits=(16, 4))
    closed_period_id = fields.Many2one('combine.cost.close', string='Cost Close', readonly=True, copy=False)

    @api.depends('department_id')
    def _compute_next(self):
        for batch in self:
            batch.next_department_id = batch.next_department_id or batch.department_id.next_department_id

    @api.depends('company_id')
    def _compute_store_location(self):
        for batch in self:
            if not batch.store_location_id:
                wh = self.env['stock.warehouse'].search([('company_id', '=', batch.company_id.id)], limit=1)
                batch.store_location_id = wh.lot_stock_id

    @api.depends('material_cost', 'conversion_actual', 'std_material', 'conversion_std', 'qty_produced')
    def _compute_costs(self):
        for b in self:
            b.actual_cost = b.material_cost + b.conversion_actual
            b.std_cost = b.std_material + b.conversion_std
            b.variance = b.actual_cost - b.std_cost
            b.actual_unit_cost = b.actual_cost / b.qty_produced if b.qty_produced else 0.0
            b.std_unit_cost = b.std_cost / b.qty_produced if b.qty_produced else 0.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('combine.production.batch') or _('New')
        return super().create(vals_list)

    @api.onchange('product_id', 'date')
    def _onchange_product_recipe(self):
        """Prefill the inputs from the cost card's recipe (standard quantities)."""
        if self.state != 'draft' or not self.product_id or self.input_ids:
            return
        card = self.env['combine.cost.card']._card_for(self.product_id, self.date)
        if card and card.kind == 'produced':
            self.input_ids = [Command.create({'product_id': l.product_id.id, 'qty': 0.0}) for l in card.line_ids]

    # ------------------------------------------------------------------ complete
    def action_complete(self):
        Ledger = self.env['combine.dept.ledger'].sudo()
        Card = self.env['combine.cost.card']
        for b in self:
            if b.state != 'draft':
                continue
            if b.qty_produced <= 0:
                raise UserError(_('%s: enter the good output quantity.', b.name))
            inputs = b.input_ids.filtered(lambda l: l.qty > 0)
            if not inputs:
                raise UserError(_('%s: enter what was consumed.', b.name))
            dept = b.department_id
            # consume inputs from the department's own stock at its average actual cost
            short, rows, material = [], [], 0.0
            for line in inputs:
                qty = line.uom_id._compute_quantity(line.qty, line.product_id.uom_id)
                have_qty, have_value = Ledger._balance(dept, line.product_id, b.date)
                if float_compare(qty, have_qty, precision_rounding=line.product_id.uom_id.rounding) > 0:
                    short.append(_('%(item)s: needs %(need)s, department has %(have)s',
                                   item=line.product_id.display_name, need=round(qty, 4), have=round(have_qty, 4)))
                    continue
                unit = have_value / have_qty if have_qty else 0.0
                value = unit * qty
                line.write({'actual_price': unit, 'value': value,
                            'std_price': Card._std_cost(line.product_id, b.date)})
                material += value
                rows.append({'date': b.date, 'department_id': dept.id, 'product_id': line.product_id.id, 'qty': -qty,
                             'value': -value, 'kind': 'consume', 'batch_id': b.id, 'company_id': b.company_id.id})
            if short:
                raise UserError(_('Not enough in %(dept)s:\n%(lines)s', dept=dept.name, lines='\n'.join(short)))
            # standard for the output
            card = Card._card_for(b.product_id, b.date)
            std_lines = {l.product_id: l.qty for l in card.line_ids} if card and card.kind == 'produced' else {}
            for line in inputs:
                line.std_qty = std_lines.get(line.product_id, 0.0) * b.qty_produced
            std_material = sum(l.qty * Card._std_cost(l.product_id, b.date) for l in card.line_ids) * b.qty_produced \
                if card and card.kind == 'produced' else 0.0
            conv_std = (card.conversion_cost if card else 0.0) * b.qty_produced
            transfer_value = material + conv_std
            out_qty = b.qty_produced
            rows.append({'date': b.date, 'department_id': dept.id, 'product_id': b.product_id.id, 'qty': out_qty,
                         'value': transfer_value, 'kind': 'produce', 'batch_id': b.id, 'company_id': b.company_id.id})
            if b.qty_waste and b.waste_product_id:
                rows.append({'date': b.date, 'department_id': dept.id, 'product_id': b.waste_product_id.id,
                             'qty': b.qty_waste, 'value': 0.0, 'kind': 'waste', 'batch_id': b.id, 'company_id': b.company_id.id})
            if b.destination == 'next':
                if not b.next_department_id or b.next_department_id == dept:
                    raise UserError(_('%s: choose the department the output goes to.', b.name))
                rows += [
                    {'date': b.date, 'department_id': dept.id, 'product_id': b.product_id.id, 'qty': -out_qty, 'value': -transfer_value,
                     'kind': 'transfer_out', 'batch_id': b.id, 'other_department_id': b.next_department_id.id, 'company_id': b.company_id.id},
                    {'date': b.date, 'department_id': b.next_department_id.id, 'product_id': b.product_id.id, 'qty': out_qty,
                     'value': transfer_value, 'kind': 'transfer_in', 'batch_id': b.id, 'other_department_id': dept.id, 'company_id': b.company_id.id},
                ]
            elif b.destination == 'store':
                rows.append({'date': b.date, 'department_id': dept.id, 'product_id': b.product_id.id, 'qty': -out_qty,
                             'value': -transfer_value, 'kind': 'to_store', 'batch_id': b.id, 'company_id': b.company_id.id})
            Ledger.create(rows)
            b.write({'state': 'done', 'card_id': card.id if card else False, 'material_cost': material,
                     'conversion_std': conv_std, 'conversion_actual': conv_std, 'std_material': std_material,
                     'transfer_value': transfer_value})
            if b.destination == 'store':
                b._receive_into_store()
        return True

    def _receive_into_store(self):
        """Output into the warehouse through a normal stock move, valued at the
        batch's transfer value (Odoo's production-value hook)."""
        self.ensure_one()
        src = self.department_id.location_id
        if not src or not self.store_location_id:
            raise UserError(_('%s: department location / receiving location missing.', self.name))
        move = self.env['stock.move'].create({
            'product_id': self.product_id.id, 'product_uom_qty': self.qty_produced, 'product_uom': self.product_id.uom_id.id,
            'location_id': src.id, 'location_dest_id': self.store_location_id.id, 'origin': self.name,
            'company_id': self.company_id.id, 'x_production_batch_id': self.id,
        })
        move._action_confirm()
        move.quantity = self.qty_produced
        move.picked = True
        move._action_done()
        self.stock_move_id = move

    def action_cancel(self):
        if any(b.state == 'done' for b in self):
            raise UserError(_('A completed batch cannot be cancelled.'))
        self.write({'state': 'cancel'})

    def action_draft(self):
        self.filtered(lambda b: b.state == 'cancel').write({'state': 'draft'})

    # ------------------------------------------------------------------ print
    def _print_title(self):
        return 'Production Batch Report'

    def _print_info(self):
        dest = {'next': self.next_department_id.name, 'store': self.store_location_id.display_name,
                'stay': self.department_id.name}.get(self.destination) or '-'
        return [('Batch No.', self.name), ('Date', self._print_date(self.date)), ('Department', self.department_id.name),
                ('Lot / Ref.', self.lot_no or '-'), ('Output', '%s  %s %s' % (self.product_id.display_name, self._n(self.qty_produced), self.uom_id.name or '')),
                ('Waste', '%s %s' % (self._n(self.qty_waste), self.uom_id.name or '')), ('Transferred To', dest),
                ('Shift', self.shift or '-'), ('Status', dict(self._fields['state'].selection)[self.state])]

    @staticmethod
    def _n(v, d=2):
        return f'{v:,.{d}f}'

    def _print_columns(self):
        return [('Sr.', 'c'), ('Input Item', ''), ('Actual Qty', 'n'), ('Std. Qty', 'n'), ('UoM', 'c'),
                ('Actual Rate', 'n'), ('Std. Rate', 'n'), ('Actual Value', 'n'), ('Std. Value', 'n'), ('Variance', 'n')]

    def _print_rows(self):
        rows = []
        for i, l in enumerate(self.input_ids.filtered(lambda l: l.qty > 0), 1):
            std_value = l.std_qty * l.std_price
            rows.append([i, l.product_id.display_name, self._n(l.qty), self._n(l.std_qty), l.uom_id.name,
                         self._n(l.actual_price, 4), self._n(l.std_price, 4), self._n(l.value), self._n(std_value),
                         self._n(l.value - std_value)])
        n = len(rows)
        rows.append([n + 1, 'Conversion (power, wages, overheads)', '', '', '', '', '', self._n(self.conversion_actual),
                     self._n(self.conversion_std), self._n(self.conversion_actual - self.conversion_std)])
        return rows

    def _print_totals(self):
        return {7: self._n(self.actual_cost), 8: self._n(self.std_cost), 9: self._n(self.variance)}

    def _print_signatures(self):
        return ['Prepared by', 'Department Head', 'Cost Accountant']


class ProductionBatchInput(models.Model):
    _name = 'combine.production.batch.input'
    _description = 'Production Batch Input'

    batch_id = fields.Many2one('combine.production.batch', required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one('product.product', string='Input Item', required=True)
    uom_id = fields.Many2one('uom.uom', string='UoM', compute='_compute_uom', store=True, readonly=False, precompute=True)
    qty = fields.Float(string='Quantity Consumed', digits='Product Unit')
    available_qty = fields.Float(string='In Department', compute='_compute_available', digits='Product Unit')
    std_qty = fields.Float(string='Std. Quantity', digits='Product Unit', readonly=True)
    actual_price = fields.Float(string='Actual Rate', digits=(16, 4), readonly=True)
    std_price = fields.Float(string='Std. Rate', digits=(16, 4), readonly=True)
    value = fields.Float(string='Actual Value', digits=(16, 2), readonly=True)

    @api.depends('product_id')
    def _compute_uom(self):
        for line in self:
            line.uom_id = line.uom_id or line.product_id.uom_id

    @api.depends('product_id', 'batch_id.department_id', 'batch_id.date')
    def _compute_available(self):
        Ledger = self.env['combine.dept.ledger']
        for line in self:
            if line.product_id and line.batch_id.department_id:
                line.available_qty = Ledger._balance(line.batch_id.department_id, line.product_id, line.batch_id.date,
                                                     exclude_batch=line.batch_id if line.batch_id.state == 'done' else None)[0]
            else:
                line.available_qty = 0.0


class StockMove(models.Model):
    _inherit = 'stock.move'

    x_production_batch_id = fields.Many2one('combine.production.batch', string='Production Batch', readonly=True, index='btree_not_null')

    def _get_value_from_production(self, quantity, at_date=None):
        if self.x_production_batch_id and self.x_production_batch_id.qty_produced:
            batch = self.x_production_batch_id
            return {'value': batch.transfer_value * quantity / batch.qty_produced, 'quantity': quantity,
                    'description': _('Value from production batch %s', batch.name)}
        return super()._get_value_from_production(quantity, at_date)


# ============================================================ month-end WIP count
class WipCount(models.Model):
    """Physical count of what is lying in a department (material + work in
    process). The difference to the book balance is posted to the department
    ledger as a count adjustment at the average cost."""
    _name = 'combine.wip.count'
    _description = 'Department Stock / WIP Count'
    _inherit = ['mail.thread', 'combine.stores.print.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(default=lambda self: _('New'), readonly=True, copy=False)
    date = fields.Date(required=True, default=fields.Date.context_today)
    department_id = fields.Many2one('combine.production.department', required=True)
    state = fields.Selection([('draft', 'Draft'), ('done', 'Posted')], default='draft', required=True, tracking=True)
    line_ids = fields.One2many('combine.wip.count.line', 'count_id', copy=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('combine.wip.count') or _('New')
        return super().create(vals_list)

    def action_load_book(self):
        """Fill the lines with every item the department holds per the book."""
        Ledger = self.env['combine.dept.ledger']
        for count in self.filtered(lambda c: c.state == 'draft'):
            rows = Ledger._read_group([('department_id', '=', count.department_id.id), ('date', '<=', count.date)],
                                      ['product_id'], ['qty:sum'])
            have = count.line_ids.product_id
            count.write({'line_ids': [Command.create({'product_id': p.id, 'counted_qty': q})
                                      for p, q in rows if p not in have and not float_is_zero(q, precision_digits=4)]})

    def action_post(self):
        Ledger = self.env['combine.dept.ledger'].sudo()
        for count in self.filtered(lambda c: c.state == 'draft'):
            rows = []
            for line in count.line_ids:
                book_qty, book_value = Ledger._balance(count.department_id, line.product_id, count.date)
                diff = line.counted_qty - book_qty
                if float_is_zero(diff, precision_digits=4):
                    continue
                unit = book_value / book_qty if book_qty else self.env['combine.cost.card']._std_cost(line.product_id, count.date)
                rows.append({'date': count.date, 'department_id': count.department_id.id, 'product_id': line.product_id.id,
                             'qty': diff, 'value': diff * unit, 'kind': 'adjust', 'count_id': count.id, 'company_id': count.company_id.id})
            Ledger.create(rows)
            count.state = 'done'

    def _print_title(self):
        return 'Department Stock / WIP Count'

    def _print_info(self):
        return [('Count No.', self.name), ('Date', self._print_date(self.date)), ('Department', self.department_id.name)]

    def _print_columns(self):
        return [('Sr.', 'c'), ('Item', ''), ('Book Qty', 'n'), ('Counted Qty', 'n'), ('Difference', 'n'), ('UoM', 'c')]

    def _print_rows(self):
        return [[i, l.product_id.display_name, f'{l.book_qty:,.2f}', f'{l.counted_qty:,.2f}', f'{l.counted_qty - l.book_qty:,.2f}',
                 l.product_id.uom_id.name] for i, l in enumerate(self.line_ids, 1)]

    def _print_totals(self):
        return {}

    def _print_signatures(self):
        return ['Counted by', 'Department Head', 'Cost Accountant']


class WipCountLine(models.Model):
    _name = 'combine.wip.count.line'
    _description = 'Department Stock / WIP Count Line'

    count_id = fields.Many2one('combine.wip.count', required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one('product.product', string='Item', required=True)
    book_qty = fields.Float(string='Book Qty', compute='_compute_book', digits='Product Unit')
    counted_qty = fields.Float(string='Counted Qty', digits='Product Unit')

    @api.depends('product_id', 'count_id.department_id', 'count_id.date', 'count_id.state')
    def _compute_book(self):
        Ledger = self.env['combine.dept.ledger']
        for line in self:
            if line.product_id and line.count_id.department_id:
                qty = Ledger._balance(line.count_id.department_id, line.product_id, line.count_id.date)[0]
                if line.count_id.state == 'done':
                    adj = Ledger.search([('count_id', '=', line.count_id.id), ('product_id', '=', line.product_id.id)])
                    qty -= sum(adj.mapped('qty'))
                line.book_qty = qty
            else:
                line.book_qty = 0.0


# ============================================================ month-end cost close
class CostClose(models.Model):
    """Month-end: each department's actual conversion cost (from its cost
    centre in the books, plus any manual amount) spread over the batches it
    completed in the month by output quantity. Gives the actual cost and the
    conversion variance per batch."""
    _name = 'combine.cost.close'
    _description = 'Month-end Cost Close'
    _inherit = ['mail.thread']
    _order = 'date_to desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    date_from = fields.Date(required=True, default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date(required=True, default=fields.Date.context_today)
    state = fields.Selection([('draft', 'Draft'), ('done', 'Closed')], default='draft', required=True, tracking=True)
    line_ids = fields.One2many('combine.cost.close.line', 'close_id', copy=False)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')

    @api.depends('date_from', 'date_to')
    def _compute_name(self):
        for c in self:
            c.name = _('Cost Close %(f)s to %(t)s', f=c.date_from, t=c.date_to)

    def action_load(self):
        """One line per department: actual conversion from the books, output, standard conversion."""
        for close in self.filtered(lambda c: c.state == 'draft'):
            close.line_ids.unlink()
            vals = []
            for dept in self.env['combine.production.department'].search([('company_id', '=', close.company_id.id)]):
                batches = close._batches(dept)
                actual = 0.0
                if dept.analytic_account_id:
                    lines = self.env['account.analytic.line'].search([
                        ('auto_account_id', '=', dept.analytic_account_id.id) if 'auto_account_id' in self.env['account.analytic.line']._fields
                        else ('account_id', '=', dept.analytic_account_id.id),
                        ('date', '>=', close.date_from), ('date', '<=', close.date_to)])
                    actual = -sum(lines.mapped('amount'))
                if batches or actual:
                    vals.append({'department_id': dept.id, 'actual_books': actual})
            close.write({'line_ids': [Command.create(v) for v in vals]})

    def _batches(self, dept):
        return self.env['combine.production.batch'].search([
            ('department_id', '=', dept.id), ('state', '=', 'done'),
            ('date', '>=', self.date_from), ('date', '<=', self.date_to)])

    def action_close(self):
        for close in self.filtered(lambda c: c.state == 'draft'):
            if not close.line_ids:
                close.action_load()
            for line in close.line_ids:
                batches = close._batches(line.department_id)
                total_qty = sum(batches.mapped('qty_produced'))
                for b in batches:
                    share = line.actual_total * b.qty_produced / total_qty if total_qty else 0.0
                    b.write({'conversion_actual': share, 'closed_period_id': close.id})
            close.state = 'done'

    def action_reopen(self):
        for close in self.filtered(lambda c: c.state == 'done'):
            batches = self.env['combine.production.batch'].search([('closed_period_id', '=', close.id)])
            for b in batches:
                b.write({'conversion_actual': b.conversion_std, 'closed_period_id': False})
            close.state = 'draft'


class CostCloseLine(models.Model):
    _name = 'combine.cost.close.line'
    _description = 'Month-end Cost Close Line'

    close_id = fields.Many2one('combine.cost.close', required=True, ondelete='cascade', index=True)
    currency_id = fields.Many2one(related='close_id.currency_id')
    department_id = fields.Many2one('combine.production.department', required=True)
    actual_books = fields.Monetary(string='From Books (Cost Centre)')
    actual_manual = fields.Monetary(string='Other / Manual')
    actual_total = fields.Monetary(string='Actual Conversion', compute='_compute_totals')
    output_qty = fields.Float(string='Output', compute='_compute_totals', digits='Product Unit')
    std_conversion = fields.Monetary(string='Std. Conversion', compute='_compute_totals')
    variance = fields.Monetary(string='Conversion Variance', compute='_compute_totals')
    actual_rate = fields.Float(string='Actual / Unit', compute='_compute_totals', digits=(16, 4))

    @api.depends('actual_books', 'actual_manual', 'department_id', 'close_id.date_from', 'close_id.date_to')
    def _compute_totals(self):
        for line in self:
            batches = line.close_id._batches(line.department_id) if line.department_id else self.env['combine.production.batch']
            line.actual_total = line.actual_books + line.actual_manual
            line.output_qty = sum(batches.mapped('qty_produced'))
            line.std_conversion = sum(batches.mapped('conversion_std'))
            line.variance = line.actual_total - line.std_conversion
            line.actual_rate = line.actual_total / line.output_qty if line.output_qty else 0.0
