from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .stores_print import num


class GatePassOut(models.Model):
    _name = 'combine.gate.pass.out'
    _description = 'Gate Pass Outward'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'combine.stores.print.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(default=lambda self: _('New'), readonly=True, copy=False)
    pass_type = fields.Selection([
        ('sale', 'Sales Delivery'),
        ('purchase_return', 'Rejected - Return to Vendor'),
        ('other', 'Other (repair, sample, ...)'),
    ], string='Type', default='sale', required=True, tracking=True)
    date = fields.Datetime(string='Gate Out', default=fields.Datetime.now, required=True)
    partner_id = fields.Many2one('res.partner', string='Party', required=True, tracking=True)
    picking_id = fields.Many2one('stock.picking', string='Delivery', domain="[('picking_type_code', '=', 'outgoing'), ('state', '=', 'done')]")
    sale_id = fields.Many2one(related='picking_id.sale_id', store=True, string='Sales Order')
    invoice_ref = fields.Char(string='Invoice Ref.', tracking=True)
    reference = fields.Char(string='Other Ref.')
    inspection_id = fields.Many2one('combine.inspection', string='Inspection', ondelete='set null')
    vehicle_no = fields.Char(string='Vehicle No.')
    driver = fields.Char()
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    state = fields.Selection([('draft', 'Draft'), ('out', 'Gone Out'), ('cancel', 'Cancelled')],
                             default='draft', required=True, tracking=True, copy=False)
    line_ids = fields.One2many('combine.gate.pass.out.line', 'gate_pass_id', string='Items', copy=True)
    note = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('combine.gate.pass.out') or _('New')
        return super().create(vals_list)

    @api.onchange('picking_id')
    def _onchange_picking_id(self):
        if self.picking_id:
            vals = self._values_from_delivery(self.picking_id)
            self.partner_id = vals['partner_id']
            self.invoice_ref = vals['invoice_ref']
            self.line_ids = [(5, 0, 0)] + vals['line_ids']

    @api.model
    def _values_from_delivery(self, picking):
        invoices = picking.sale_id.invoice_ids.filtered(lambda m: m.state == 'posted' and m.move_type == 'out_invoice')
        if 'x_delivery_challan_id' in invoices._fields:
            invoices = invoices.filtered(lambda m: m.x_delivery_challan_id == picking) or invoices
        return {
            'pass_type': 'sale',
            'partner_id': picking.partner_id.commercial_partner_id.id,
            'picking_id': picking.id,
            'invoice_ref': ', '.join(invoices.mapped('name')) or False,
            'line_ids': [(0, 0, {'product_id': m.product_id.id, 'uom_id': m.product_uom.id, 'qty': m.quantity})
                         for m in picking.move_ids.filtered(lambda m: m.state == 'done' and m.quantity)],
        }

    def action_gate_out(self):
        for gp in self:
            if not gp.line_ids:
                raise UserError(_('Add the items going out.'))
            gp.state = 'out'

    def action_cancel(self):
        self.write({'state': 'cancel'})

    def action_draft(self):
        self.filtered(lambda g: g.state == 'cancel').write({'state': 'draft'})

    # print
    def _print_title(self):
        return 'Gate Pass Outward'

    def _print_info(self):
        return [('OGP No.', self.name), ('Gate Out', fields.Datetime.to_string(fields.Datetime.context_timestamp(self, self.date))[:16]),
                ('Type', dict(self._fields['pass_type'].selection)[self.pass_type]),
                ('Delivery', self.picking_id.name or '-'), ('Invoice Ref.', self.invoice_ref or '-'),
                ('Vehicle No.', self.vehicle_no or '-'), ('Driver', self.driver or '-'), ('Other Ref.', self.reference or '-')]

    def _print_party(self):
        return self.partner_id

    def _print_columns(self):
        return [('Sr.', 'c'), ('Item', ''), ('Quantity', 'n'), ('UoM', 'c'), ('Packages', 'n'),
                ('Gross Wt.', 'n'), ('Tare Wt.', 'n'), ('Net Wt.', 'n'), ('Remarks', '')]

    def _print_rows(self):
        return [[i, l.product_id.display_name, num(l.qty), l.uom_id.name, l.packages or '-', num(l.gross_weight),
                 num(l.tare_weight), num(l.net_weight), l.note or ''] for i, l in enumerate(self.line_ids, 1)]

    def _print_totals(self):
        lines = self.line_ids
        return {2: num(sum(lines.mapped('qty'))), 4: sum(lines.mapped('packages')) or '-',
                5: num(sum(lines.mapped('gross_weight'))), 6: num(sum(lines.mapped('tare_weight'))), 7: num(sum(lines.mapped('net_weight')))}

    def _print_signatures(self):
        return ['Store Incharge', 'Gate Officer', 'Driver / Receiver']


class GatePassOutLine(models.Model):
    _name = 'combine.gate.pass.out.line'
    _description = 'Gate Pass Outward Line'
    _inherit = ['combine.gate.weight.mixin']

    gate_pass_id = fields.Many2one('combine.gate.pass.out', required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one('product.product', string='Item', required=True)
    uom_id = fields.Many2one('uom.uom', string='UoM', compute='_compute_uom', store=True, readonly=False, precompute=True, required=True)
    qty = fields.Float(string='Quantity', digits='Product Unit')
    note = fields.Char(string='Remarks')

    @api.depends('product_id')
    def _compute_uom(self):
        for line in self:
            line.uom_id = line.uom_id or line.product_id.uom_id


class Combine001GatePass(models.Model):
    """House-style print for combine001's own Gate Pass (made from a Delivery
    Challan). Print methods only - no fields, so nothing changes in its table."""
    _name = 'combine001.gate.pass'
    _inherit = ['combine001.gate.pass', 'combine.stores.print.mixin']

    def _print_title(self):
        return 'Gate Pass'

    def _print_info(self):
        invoices = self.sale_order_id.invoice_ids.filtered(lambda m: m.state == 'posted' and m.move_type == 'out_invoice')
        return [('Gate Pass No.', self.name),
                ('Date', fields.Datetime.to_string(fields.Datetime.context_timestamp(self, self.date))[:16] if self.date else ''),
                ('Delivery Challan', self.picking_id.name or '-'),
                ('Contract', self.sale_order_id.name or '-'),
                ('Invoice Ref.', ', '.join(invoices.mapped('name')) or '-'),
                ('GST Status', dict(self._fields['x_gst_status']._description_selection(self.env)).get(self.x_gst_status, '-') if self.x_gst_status else '-')]

    def _print_party(self):
        return self.partner_id

    def _print_columns(self):
        return [('Sr.', 'c'), ('Item', ''), ('Quantity Delivered', 'n'), ('UoM', 'c'), ('Weight', 'n')]

    def _print_rows(self):
        rows = []
        for i, line in enumerate(self.line_ids, 1):
            weight = (line.product_id.weight or 0.0) * line.product_uom._compute_quantity(line.quantity, line.product_id.uom_id)
            rows.append([i, line.product_id.display_name, num(line.quantity), line.product_uom.name, num(weight)])
        return rows

    def _print_totals(self):
        weight = sum((l.product_id.weight or 0.0) * l.product_uom._compute_quantity(l.quantity, l.product_id.uom_id) for l in self.line_ids)
        return {2: num(sum(self.line_ids.mapped('quantity'))), 4: num(weight)}

    def _print_note(self):
        return False

    def _print_signatures(self):
        return ['Store Incharge', 'Gate Officer', 'Driver / Receiver']
