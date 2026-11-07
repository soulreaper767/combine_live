from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .stores_print import num


class DemandNote(models.Model):
    _name = 'combine.demand.note'
    _description = 'Demand Note'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'combine.stores.print.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(default=lambda self: _('New'), readonly=True, copy=False)
    date = fields.Date(default=fields.Date.context_today, required=True, tracking=True)
    date_required = fields.Date(string='Required By', tracking=True)
    user_id = fields.Many2one('res.users', string='Requested By', default=lambda self: self.env.user, required=True)
    department = fields.Char()
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    state = fields.Selection([('draft', 'Draft'), ('submitted', 'Submitted'), ('cancel', 'Cancelled')],
                             default='draft', required=True, tracking=True, copy=False)
    procurement_status = fields.Selection([
        ('pending', 'Pending'), ('partial', 'Partly Ordered'), ('ordered', 'Ordered'),
        ('partly_received', 'Partly Received'), ('received', 'Received'),
    ], compute='_compute_procurement_status', store=True, string='Procurement')
    line_ids = fields.One2many('combine.demand.note.line', 'demand_id', string='Items', copy=True)
    purchase_ids = fields.Many2many('purchase.order', compute='_compute_purchase_ids', string='Purchase Orders')
    purchase_count = fields.Integer(compute='_compute_purchase_ids')
    note = fields.Text()

    @api.depends('line_ids.ordered_qty', 'line_ids.received_qty', 'line_ids.qty')
    def _compute_procurement_status(self):
        for dn in self:
            lines = dn.line_ids
            if not lines or not any(lines.mapped('ordered_qty')):
                dn.procurement_status = 'pending'
            elif all(l.received_qty >= l.qty for l in lines):
                dn.procurement_status = 'received'
            elif any(lines.mapped('received_qty')):
                dn.procurement_status = 'partly_received'
            elif all(l.ordered_qty >= l.qty for l in lines):
                dn.procurement_status = 'ordered'
            else:
                dn.procurement_status = 'partial'

    def _compute_purchase_ids(self):
        for dn in self:
            orders = dn.line_ids.purchase_line_ids.order_id
            dn.purchase_ids = orders
            dn.purchase_count = len(orders)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('combine.demand.note') or _('New')
        return super().create(vals_list)

    def action_submit(self):
        for dn in self:
            if not dn.line_ids:
                raise UserError(_('This demand note has no items. Add the items needed (item and quantity) in the lines, then click Submit.'))
        self.write({'state': 'submitted'})

    def action_cancel(self):
        if any(dn.line_ids.filtered('purchase_line_ids') for dn in self):
            raise UserError(_('Purchase orders were already made from this demand note, so it cannot be changed or cancelled. Cancel those purchase orders first (open them from the demand note), then try again.'))
        self.write({'state': 'cancel'})

    def action_draft(self):
        self.filtered(lambda d: d.state == 'cancel').write({'state': 'draft'})

    def action_create_purchase(self):
        lines = self.line_ids.filtered(lambda l: l.demand_id.state == 'submitted' and l.pending_qty > 0)
        if not lines:
            raise UserError(_('Everything on the selected demand notes is already ordered. Check "Demand Status by Item" (Stores > Reporting) for what is pending.'))
        wizard = self.env['combine.demand.po.wizard'].create({
            'line_ids': [(0, 0, {
                'demand_line_id': l.id,
                'product_id': l.product_id.id,
                'qty': l.pending_qty,
                'uom_id': l.uom_id.id,
                'vendor_id': l.product_id._select_seller(quantity=l.pending_qty).partner_id.id,
                'price_unit': l.product_id._select_seller(quantity=l.pending_qty).price or l.product_id.standard_price,
            }) for l in lines],
        })
        return {'type': 'ir.actions.act_window', 'name': _('Create Purchase Orders'), 'res_model': wizard._name,
                'res_id': wizard.id, 'view_mode': 'form', 'target': 'new'}

    def action_view_purchases(self):
        return {'type': 'ir.actions.act_window', 'name': _('Purchase Orders'), 'res_model': 'purchase.order',
                'view_mode': 'list,form', 'domain': [('id', 'in', self.purchase_ids.ids)]}

    # print
    def _print_info(self):
        return [('Demand No.', self.name), ('Date', self._print_date(self.date)),
                ('Requested By', self.user_id.name), ('Department', self.department or '-'),
                ('Required By', self._print_date(self.date_required) or '-'), ('Status', dict(self._fields['state'].selection)[self.state])]

    def _print_columns(self):
        return [('Sr.', 'c'), ('Item', ''), ('Quantity', 'n'), ('UoM', 'c'), ('Ordered', 'n'), ('Received', 'n'), ('Remarks', '')]

    def _print_rows(self):
        return [[i, l.product_id.display_name, num(l.qty), l.uom_id.name, num(l.ordered_qty), num(l.received_qty), l.note or '']
                for i, l in enumerate(self.line_ids, 1)]

    def _print_signatures(self):
        return ['Requested by', 'Store Incharge', 'Approved by']


class DemandNoteLine(models.Model):
    _name = 'combine.demand.note.line'
    _description = 'Demand Note Line'
    _order = 'demand_id, sequence, id'

    demand_id = fields.Many2one('combine.demand.note', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one('product.product', string='Item', required=True, domain=[('purchase_ok', '=', True)])
    qty = fields.Float(string='Quantity', required=True, digits='Product Unit')
    uom_id = fields.Many2one('uom.uom', string='UoM', compute='_compute_uom', store=True, readonly=False, precompute=True, required=True)
    note = fields.Char(string='Remarks')
    purchase_line_ids = fields.One2many('purchase.order.line', 'x_demand_line_id', string='Purchase Lines')
    ordered_qty = fields.Float(compute='_compute_progress', store=True, digits='Product Unit')
    received_qty = fields.Float(compute='_compute_progress', store=True, digits='Product Unit')
    pending_qty = fields.Float(string='Pending', compute='_compute_progress', store=True, digits='Product Unit')
    state = fields.Selection(related='demand_id.state', store=True)

    @api.depends('product_id')
    def _compute_uom(self):
        for line in self:
            line.uom_id = line.uom_id or line.product_id.uom_id

    @api.depends('qty', 'uom_id', 'purchase_line_ids.product_qty', 'purchase_line_ids.qty_received',
                 'purchase_line_ids.order_id.state', 'purchase_line_ids.product_uom_id')
    def _compute_progress(self):
        for line in self:
            ordered = received = 0.0
            for pol in line.purchase_line_ids.filtered(lambda p: p.order_id.state != 'cancel'):
                ordered += pol.product_uom_id._compute_quantity(pol.product_qty, line.uom_id, raise_if_failure=False)
                received += pol.product_uom_id._compute_quantity(pol.qty_received, line.uom_id, raise_if_failure=False)
            line.ordered_qty, line.received_qty = ordered, received
            line.pending_qty = max(line.qty - ordered, 0.0)
