from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero

from .conversion_process import CHARGE_BASIS, RECOVERY_BASIS

JOBWORK_LOCATION = 'Job Work at Vendors'
CONVERSION_LOCATION = 'Job Work Conversion'


class ConversionOrder(models.Model):
    _name = 'combine.conversion.order'
    _description = 'Conversion Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(default=lambda self: _('New'), readonly=True, copy=False, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('sent', 'At Vendor'),
        ('done', 'Closed'),
        ('cancel', 'Cancelled'),
    ], default='draft', required=True, copy=False, tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    partner_id = fields.Many2one('res.partner', string='Vendor', required=True, tracking=True,
                                 compute='_compute_from_process', store=True, readonly=False, precompute=True)
    process_id = fields.Many2one('combine.conversion.process', string='Process', required=True, tracking=True)
    category_id = fields.Many2one(related='process_id.category_id', store=True, string='Process Category')
    date = fields.Date(string='Date Sent', default=fields.Date.context_today, required=True)
    date_closed = fields.Date(readonly=True, copy=False)
    warehouse_id = fields.Many2one(
        'stock.warehouse', required=True, check_company=True,
        default=lambda self: self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1))
    output_product_id = fields.Many2one('product.product', string='Output Item', required=True,
                                        domain=[('is_storable', '=', True)], tracking=True,
                                        compute='_compute_from_process', store=True, readonly=False, precompute=True)
    output_uom_id = fields.Many2one(related='output_product_id.uom_id', string='Output UoM')

    standard_yield = fields.Float(string='Standard Yield %', digits=(5, 2),
                                  compute='_compute_from_process', store=True, readonly=False, precompute=True)
    wastage_tolerance = fields.Float(string='Wastage Tolerance %', digits=(5, 2),
                                     compute='_compute_from_process', store=True, readonly=False, precompute=True)
    recovery_basis = fields.Selection(RECOVERY_BASIS, string='Excess Wastage Recovery',
                                      compute='_compute_from_process', store=True, readonly=False, precompute=True)
    recovery_rate = fields.Float(string='Recovery Rate / Unit', digits='Product Price',
                                 compute='_compute_from_process', store=True, readonly=False, precompute=True)
    waste_product_id = fields.Many2one('product.product', string='Waste Item',
                                       compute='_compute_from_process', store=True, readonly=False, precompute=True)
    waste_rate = fields.Float(string='Waste Value / Unit', digits='Product Price',
                              compute='_compute_from_process', store=True, readonly=False, precompute=True)

    input_line_ids = fields.One2many('combine.conversion.input', 'order_id', string='Material Sent', copy=True)
    charge_line_ids = fields.One2many('combine.conversion.charge', 'order_id', string='Charges', copy=True,
                                      compute='_compute_charge_lines', store=True, readonly=False, precompute=True)
    receipt_line_ids = fields.One2many('combine.conversion.receipt', 'order_id', string='Receipts', copy=False)

    previous_order_id = fields.Many2one('combine.conversion.order', string='Previous Process', copy=False, index='btree_not_null')
    next_order_ids = fields.One2many('combine.conversion.order', 'previous_order_id', string='Next Processes')
    dispatch_picking_id = fields.Many2one('stock.picking', string='Dispatch Transfer', readonly=True, copy=False)
    consumption_move_ids = fields.Many2many('stock.move', 'combine_conversion_consumption_rel', string='Consumption Moves',
                                            readonly=True, copy=False)
    bill_id = fields.Many2one('account.move', string='Charges Bill', readonly=True, copy=False)
    debit_note_id = fields.Many2one('account.move', string='Recovery Debit Note', readonly=True, copy=False)
    note = fields.Html()

    # ---- quantities (in the output item's unit of measure) -------------
    input_qty = fields.Float(string='Qty Sent', compute='_compute_totals', store=True, digits='Product Unit')
    input_value = fields.Monetary(string='Cost of Material Sent', compute='_compute_totals', store=True)
    expected_qty = fields.Float(string='Standard Output', compute='_compute_totals', store=True, digits='Product Unit')
    standard_wastage_qty = fields.Float(string='Standard Wastage', compute='_compute_totals', store=True, digits='Product Unit')
    received_qty = fields.Float(string='Qty Received', compute='_compute_totals', store=True, digits='Product Unit')
    waste_qty = fields.Float(string='Waste Returned', compute='_compute_totals', store=True, digits='Product Unit')
    actual_yield = fields.Float(string='Actual Yield %', compute='_compute_totals', store=True, digits=(5, 2), aggregator='avg')
    yield_variance = fields.Float(string='Yield Variance %', compute='_compute_totals', store=True, digits=(5, 2), aggregator='avg')
    actual_wastage_qty = fields.Float(string='Actual Wastage', compute='_compute_totals', store=True, digits='Product Unit')
    allowed_min_qty = fields.Float(string='Minimum Acceptable Output', compute='_compute_totals', store=True, digits='Product Unit')
    excess_wastage_qty = fields.Float(string='Excess Wastage', compute='_compute_totals', store=True, digits='Product Unit')
    # ---- costing ----------------------------------------------------------
    charges_amount = fields.Monetary(string='Conversion Charges', compute='_compute_totals', store=True)
    recovery_amount = fields.Monetary(string='Recovery from Vendor', compute='_compute_totals', store=True)
    waste_value = fields.Monetary(string='Waste Value', compute='_compute_totals', store=True)
    total_cost = fields.Monetary(string='Total Cost', compute='_compute_totals', store=True)
    unit_cost = fields.Float(string='Actual Cost / Unit', compute='_compute_totals', store=True, aggregator='avg',
                             digits='Product Price')
    standard_unit_cost = fields.Float(string='Standard Cost / Unit', compute='_compute_totals', store=True, aggregator='avg',
                                      digits='Product Price')

    _PROCESS_FIELDS = ('partner_id', 'output_product_id', 'standard_yield', 'wastage_tolerance',
                       'recovery_basis', 'recovery_rate', 'waste_product_id', 'waste_rate')

    # ------------------------------------------------------------------ compute
    @api.depends('process_id')
    def _compute_from_process(self):
        for order in self:
            process = order.process_id
            if not process or order.state not in (False, 'draft'):
                order.update({f: order[f] for f in self._PROCESS_FIELDS})
                continue
            order.update({
                'partner_id': order.partner_id or process.vendor_id,
                'output_product_id': order.output_product_id or process.output_product_id,
                'standard_yield': process.standard_yield,
                'wastage_tolerance': process.wastage_tolerance,
                'recovery_basis': process.recovery_basis,
                'recovery_rate': process.recovery_rate,
                'waste_product_id': process.waste_product_id,
                'waste_rate': process.waste_rate,
            })

    @api.depends('process_id')
    def _compute_charge_lines(self):
        for order in self:
            if order.state not in (False, 'draft') or not order.process_id:
                order.charge_line_ids = order.charge_line_ids
                continue
            order.charge_line_ids = [Command.clear()] + [Command.create({
                'name': c.name, 'basis': c.basis, 'rate': c.rate, 'sequence': c.sequence,
            }) for c in order.process_id.charge_line_ids]

    @api.depends('input_line_ids.qty', 'input_line_ids.uom_id', 'input_line_ids.value', 'output_product_id',
                 'receipt_line_ids.qty', 'receipt_line_ids.waste_qty', 'charge_line_ids.rate', 'charge_line_ids.basis',
                 'standard_yield', 'wastage_tolerance', 'recovery_basis', 'recovery_rate', 'waste_rate')
    def _compute_totals(self):
        for order in self:
            out_uom = order.output_product_id.uom_id
            input_qty = 0.0
            for line in order.input_line_ids:
                qty = line.qty
                if out_uom and line.uom_id and line.uom_id != out_uom:
                    qty = line.uom_id._compute_quantity(line.qty, out_uom, raise_if_failure=False)
                input_qty += qty
            input_value = sum(order.input_line_ids.mapped('value'))
            expected = input_qty * order.standard_yield / 100.0
            received = sum(order.receipt_line_ids.mapped('qty'))
            waste = sum(order.receipt_line_ids.mapped('waste_qty'))
            allowed_min = input_qty * max(order.standard_yield - order.wastage_tolerance, 0.0) / 100.0
            excess = max(allowed_min - received, 0.0) if order.receipt_line_ids else 0.0
            cost_per_input = input_value / input_qty if input_qty else 0.0
            if order.recovery_basis == 'input_cost':
                recovery = excess * cost_per_input
            elif order.recovery_basis == 'fixed':
                recovery = excess * order.recovery_rate
            else:
                recovery = 0.0
            charges = std_charges = 0.0
            for charge in order.charge_line_ids:
                charges += charge._amount(input_qty, received if order.receipt_line_ids else expected)
                std_charges += charge._amount(input_qty, expected)
            waste_value = waste * order.waste_rate
            total = input_value + charges - recovery - waste_value
            order.update({
                'input_qty': input_qty,
                'input_value': input_value,
                'expected_qty': expected,
                'standard_wastage_qty': input_qty - expected,
                'received_qty': received,
                'waste_qty': waste,
                'actual_yield': received / input_qty * 100.0 if input_qty else 0.0,
                'yield_variance': (received / input_qty * 100.0 - order.standard_yield) if input_qty and order.receipt_line_ids else 0.0,
                'actual_wastage_qty': input_qty - received if order.receipt_line_ids else 0.0,
                'allowed_min_qty': allowed_min,
                'excess_wastage_qty': excess,
                'charges_amount': charges,
                'recovery_amount': recovery,
                'waste_value': waste_value,
                'total_cost': total,
                'unit_cost': total / received if received else 0.0,
                'standard_unit_cost': (input_value + std_charges) / expected if expected else 0.0,
            })

    # ------------------------------------------------------------------ crud
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('combine.conversion.order') or _('New')
        return super().create(vals_list)

    def unlink(self):
        if any(order.state not in ('draft', 'cancel') for order in self):
            raise UserError(_('Only draft or cancelled conversion orders can be deleted.'))
        return super().unlink()

    # ------------------------------------------------------------------ locations
    def _jobwork_location(self):
        self.ensure_one()
        Location = self.env['stock.location'].sudo()
        loc = Location.search([('name', '=', JOBWORK_LOCATION), ('usage', '=', 'internal'),
                               ('company_id', '=', self.company_id.id)], limit=1)
        if not loc:
            loc = Location.create({'name': JOBWORK_LOCATION, 'usage': 'internal',
                                   'location_id': self.warehouse_id.view_location_id.id,
                                   'company_id': self.company_id.id})
        return loc

    def _conversion_location(self):
        self.ensure_one()
        Location = self.env['stock.location'].sudo()
        loc = Location.search([('name', '=', CONVERSION_LOCATION), ('usage', '=', 'production'),
                               ('company_id', '=', self.company_id.id)], limit=1)
        if not loc:
            loc = Location.create({'name': CONVERSION_LOCATION, 'usage': 'production',
                                   'company_id': self.company_id.id})
        return loc

    def _done_move(self, product, qty, uom, src, dest, value=None):
        """Create and validate one stock move; `value` (incoming moves only)
        sets the move's valuation explicitly, which is what the product's
        average cost is computed from."""
        move = self.env['stock.move'].create({
            'product_id': product.id,
            'product_uom_qty': qty,
            'product_uom': uom.id,
            'location_id': src.id,
            'location_dest_id': dest.id,
            'origin': self.name,
            'company_id': self.company_id.id,
            'partner_id': self.partner_id.id,
        })
        move._action_confirm()
        move._action_assign()
        move.quantity = qty
        move.picked = True
        if value is not None:
            self.env['product.value'].sudo().create({
                'move_id': move.id, 'value': value, 'description': self.name,
            })
        move._action_done()
        return move

    # ------------------------------------------------------------------ actions
    def action_send(self):
        for order in self:
            if order.state != 'draft':
                continue
            if not order.input_line_ids:
                raise UserError(_('Add the material sent to the vendor first.'))
            if any(float_compare(line.qty, 0.0, precision_rounding=line.uom_id.rounding or 0.01) <= 0 for line in order.input_line_ids):
                raise UserError(_('Every line of material sent needs a quantity.'))
            for line in order.input_line_ids:
                line.unit_cost = line._current_unit_cost()
            stock_loc = order.warehouse_id.lot_stock_id
            picking = self.env['stock.picking'].create({
                'picking_type_id': order.warehouse_id.int_type_id.id,
                'location_id': stock_loc.id,
                'location_dest_id': order._jobwork_location().id,
                'partner_id': order.partner_id.id,
                'origin': order.name,
                'company_id': order.company_id.id,
                'move_ids': [Command.create({
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.qty,
                    'product_uom': line.uom_id.id,
                    'location_id': stock_loc.id,
                    'location_dest_id': order._jobwork_location().id,
                    'company_id': order.company_id.id,
                }) for line in order.input_line_ids],
            })
            picking.action_confirm()
            picking.action_assign()
            short = picking.move_ids.filtered(lambda m: m.state != 'assigned')
            if short:
                raise UserError(_('Not enough stock in %(loc)s to send: %(items)s',
                                  loc=stock_loc.display_name,
                                  items=', '.join(short.product_id.mapped('display_name'))))
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
                move.picked = True
            picking._action_done()
            order.write({'dispatch_picking_id': picking.id, 'state': 'sent'})
        return True

    def action_open_receive(self):
        self.ensure_one()
        if self.state != 'sent':
            raise UserError(_('Material must be sent to the vendor before anything can be received.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Receive from %s', self.partner_id.name),
            'res_model': 'combine.conversion.receive',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_order_id': self.id},
        }

    def _receive(self, qty, waste_qty=0.0, date=None, packages=0, weight_per_package=0.0, note=False):
        """Bring converted goods (and any returned waste) into stock. Valued
        provisionally at the standard cost per unit; the final cost is set
        when the order is closed."""
        self.ensure_one()
        conv = self._conversion_location()
        stock_loc = self.warehouse_id.lot_stock_id
        line_vals = {'order_id': self.id, 'date': date or fields.Date.context_today(self), 'qty': qty,
                     'waste_qty': waste_qty, 'packages': packages, 'weight_per_package': weight_per_package,
                     'note': note}
        if qty:
            line_vals['move_id'] = self._done_move(
                self.output_product_id, qty, self.output_product_id.uom_id, conv, stock_loc,
                value=qty * self.standard_unit_cost).id
        if waste_qty:
            if not self.waste_product_id:
                raise UserError(_('Set a Waste Item on the order to receive waste.'))
            line_vals['waste_move_id'] = self._done_move(
                self.waste_product_id, waste_qty, self.waste_product_id.uom_id, conv, stock_loc,
                value=waste_qty * self.waste_rate).id
        return self.env['combine.conversion.receipt'].create(line_vals)

    def action_close(self):
        for order in self:
            if order.state != 'sent':
                continue
            if float_is_zero(order.received_qty, precision_rounding=order.output_product_id.uom_id.rounding):
                raise UserError(_('Nothing has been received on %s yet.', order.name))
            # 1. the material sent is consumed by the conversion
            jobwork, conv = order._jobwork_location(), order._conversion_location()
            moves = self.env['stock.move']
            for line in order.input_line_ids:
                moves |= order._done_move(line.product_id, line.qty, line.uom_id, jobwork, conv)
            order.consumption_move_ids = [Command.set(moves.ids)]
            # 2. final cost of everything received
            order._apply_final_cost()
            # 3. vendor documents for review
            order._create_vendor_documents()
            order.write({'state': 'done', 'date_closed': fields.Date.context_today(order)})
        return True

    def _apply_final_cost(self):
        self.ensure_one()
        product = self.output_product_id
        receipt_moves = self.receipt_line_ids.move_id
        if product.cost_method == 'standard':
            # standard-cost items: fold the conversion cost into the standard price
            qty_now = product.with_company(self.company_id).qty_available
            old_qty = max(qty_now - self.received_qty, 0.0)
            if qty_now:
                new_price = (old_qty * product.standard_price + self.total_cost) / qty_now
                product.with_company(self.company_id).standard_price = new_price
            return
        ProductValue = self.env['product.value'].sudo()
        for move in receipt_moves:
            ProductValue.create({'move_id': move.id, 'value': move.quantity * self.unit_cost,
                                 'description': _('%s - final conversion cost', self.name)})
        receipt_moves._set_value()

    def _create_vendor_documents(self):
        self.ensure_one()
        product = self.env.ref('combine_conversion.product_conversion_charges', raise_if_not_found=False)
        category = self.category_id.with_company(self.company_id)
        charge_account = category.charge_account_id or self._default_charge_account(product)
        lines = []
        for charge in self.charge_line_ids.filtered(lambda c: not float_is_zero(c.amount, precision_rounding=self.currency_id.rounding)):
            qty, price = charge._bill_qty_price(self.input_qty, self.received_qty)
            vals = {'name': f'{self.name} - {charge.name}', 'quantity': qty, 'price_unit': price, 'tax_ids': [Command.clear()]}
            if product:
                vals['product_id'] = product.id
            if charge_account:
                vals['account_id'] = charge_account.id
            lines.append(Command.create(vals))
        if lines:
            self.bill_id = self.env['account.move'].create({
                'move_type': 'in_invoice', 'partner_id': self.partner_id.id, 'company_id': self.company_id.id,
                'invoice_date': fields.Date.context_today(self), 'ref': self.name, 'invoice_origin': self.name,
                'invoice_line_ids': lines,
            })
        if not float_is_zero(self.recovery_amount, precision_rounding=self.currency_id.rounding):
            vals = {'name': _('%(order)s - excess wastage %(qty).2f %(uom)s', order=self.name,
                              qty=self.excess_wastage_qty, uom=self.output_uom_id.name),
                    'quantity': 1, 'price_unit': self.recovery_amount, 'tax_ids': [Command.clear()]}
            if product:
                vals['product_id'] = product.id
            account = category.recovery_account_id or charge_account
            if account:
                vals['account_id'] = account.id
            self.debit_note_id = self.env['account.move'].create({
                'move_type': 'in_refund', 'partner_id': self.partner_id.id, 'company_id': self.company_id.id,
                'invoice_date': fields.Date.context_today(self), 'ref': self.name, 'invoice_origin': self.name,
                'invoice_line_ids': [Command.create(vals)],
            })

    def _default_charge_account(self, product):
        if product:
            account = product.with_company(self.company_id).product_tmpl_id._get_product_accounts()['expense']
            if account:
                return account
        journal = self.env['account.journal'].search([('type', '=', 'purchase'),
                                                      ('company_id', '=', self.company_id.id)], limit=1)
        if journal.default_account_id:
            return journal.default_account_id
        raise UserError(_('Set a Charges Account on the process category %s (Job Work > Configuration).',
                          self.category_id.name))

    def action_cancel(self):
        if any(order.state != 'draft' for order in self):
            raise UserError(_('Only draft conversion orders can be cancelled; material already sent has to be received and closed.'))
        self.state = 'cancel'

    def action_draft(self):
        self.filtered(lambda o: o.state == 'cancel').state = 'draft'

    def action_next_process(self):
        self.ensure_one()
        if self.state != 'done':
            raise UserError(_('Close this order before sending its output to the next process.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'combine.conversion.order',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_previous_order_id': self.id,
                'default_warehouse_id': self.warehouse_id.id,
                'default_input_line_ids': [Command.create({
                    'product_id': self.output_product_id.id,
                    'qty': self.received_qty,
                    'uom_id': self.output_product_id.uom_id.id,
                    'source_order_id': self.id,
                })],
            },
        }

    def _view_records(self, records, name):
        action = {'type': 'ir.actions.act_window', 'name': name, 'res_model': records._name}
        if len(records) == 1:
            action.update(view_mode='form', res_id=records.id)
        else:
            action.update(view_mode='list,form', domain=[('id', 'in', records.ids)])
        return action

    def action_view_dispatch(self):
        return self._view_records(self.dispatch_picking_id, _('Dispatch'))

    def action_view_bills(self):
        return self._view_records(self.bill_id | self.debit_note_id, _('Vendor Documents'))

    def action_view_next(self):
        return self._view_records(self.next_order_ids, _('Next Processes'))


class ConversionInput(models.Model):
    _name = 'combine.conversion.input'
    _description = 'Conversion Order - Material Sent'
    _order = 'order_id, sequence, id'

    order_id = fields.Many2one('combine.conversion.order', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(related='order_id.company_id')
    currency_id = fields.Many2one(related='order_id.currency_id')
    product_id = fields.Many2one('product.product', string='Item', required=True, domain=[('is_storable', '=', True)])
    size = fields.Char(string='Size / Count', help='e.g. 30/1, 20/2')
    packaging = fields.Char(help='e.g. Bags, Cones, Cartons')
    packages = fields.Integer(string='No. of Packages')
    weight_per_package = fields.Float(string='Weight / Package', digits='Stock Weight')
    net_weight = fields.Float(string='Net Weight', compute='_compute_net_weight', store=True, precompute=True,
                              digits='Stock Weight')
    qty = fields.Float(string='Quantity', required=True, digits='Product Unit',
                       compute='_compute_qty', store=True, readonly=False, precompute=True)
    uom_id = fields.Many2one('uom.uom', string='UoM', required=True,
                             compute='_compute_uom', store=True, readonly=False, precompute=True)
    source_order_id = fields.Many2one('combine.conversion.order', string='From Process',
                                      help='Output of an earlier conversion - carries that conversion\'s cost per unit.')
    unit_cost = fields.Float(string='Cost / Unit', digits=(16, 6),
                             compute='_compute_unit_cost', store=True, readonly=False, precompute=True)
    value = fields.Monetary(string='Cost', compute='_compute_value', store=True)

    @api.depends('packages', 'weight_per_package')
    def _compute_net_weight(self):
        for line in self:
            line.net_weight = line.packages * line.weight_per_package

    @api.depends('net_weight')
    def _compute_qty(self):
        for line in self:
            line.qty = line.qty or line.net_weight

    @api.depends('product_id')
    def _compute_uom(self):
        for line in self:
            line.uom_id = line.uom_id or line.product_id.uom_id

    @api.depends('product_id', 'source_order_id')
    def _compute_unit_cost(self):
        for line in self:
            if line.order_id.state in (False, 'draft'):
                line.unit_cost = line._current_unit_cost()
            else:
                line.unit_cost = line.unit_cost

    def _current_unit_cost(self):
        self.ensure_one()
        source = self.source_order_id
        if source and source.state == 'done' and source.received_qty:
            return source.total_cost / source.received_qty  # exact, not the rounded display figure
        price = self.product_id.with_company(self.order_id.company_id or self.env.company).standard_price
        if self.uom_id and self.product_id and self.uom_id != self.product_id.uom_id:
            price = self.product_id.uom_id._compute_price(price, self.uom_id)
        return price

    @api.depends('qty', 'unit_cost')
    def _compute_value(self):
        for line in self:
            line.value = line.qty * line.unit_cost


class ConversionCharge(models.Model):
    _name = 'combine.conversion.charge'
    _description = 'Conversion Order - Charge'
    _order = 'order_id, sequence, id'

    order_id = fields.Many2one('combine.conversion.order', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    currency_id = fields.Many2one(related='order_id.currency_id')
    name = fields.Char(string='Charge', required=True)
    basis = fields.Selection(CHARGE_BASIS, required=True, default='input')
    rate = fields.Float(digits='Product Price')
    amount = fields.Monetary(compute='_compute_amount', store=True)

    def _amount(self, input_qty, output_qty):
        self.ensure_one()
        if self.basis == 'fixed':
            return self.rate
        return (input_qty if self.basis == 'input' else output_qty) * self.rate

    def _bill_qty_price(self, input_qty, output_qty):
        if self.basis == 'fixed':
            return 1.0, self.rate
        return (input_qty if self.basis == 'input' else output_qty), self.rate

    @api.depends('basis', 'rate', 'order_id.input_qty', 'order_id.received_qty', 'order_id.expected_qty')
    def _compute_amount(self):
        for charge in self:
            order = charge.order_id
            output = order.received_qty if order.receipt_line_ids else order.expected_qty
            charge.amount = charge._amount(order.input_qty, output)


class ConversionReceipt(models.Model):
    _name = 'combine.conversion.receipt'
    _description = 'Conversion Order - Receipt'
    _order = 'order_id, date, id'

    order_id = fields.Many2one('combine.conversion.order', required=True, ondelete='cascade', index=True)
    date = fields.Date(required=True, default=fields.Date.context_today)
    qty = fields.Float(string='Qty Received', digits='Product Unit')
    waste_qty = fields.Float(string='Waste Returned', digits='Product Unit')
    packages = fields.Integer(string='No. of Packages')
    weight_per_package = fields.Float(string='Weight / Package', digits='Stock Weight')
    note = fields.Char()
    move_id = fields.Many2one('stock.move', string='Receipt Move', readonly=True)
    waste_move_id = fields.Many2one('stock.move', string='Waste Move', readonly=True)
