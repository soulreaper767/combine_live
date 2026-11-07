from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .stores_print import num


class GatePassWeightMixin(models.AbstractModel):
    _name = 'combine.gate.weight.mixin'
    _description = 'Packages and weights'

    packages = fields.Integer(string='Packages')
    gross_weight = fields.Float(string='Gross Wt.', digits='Stock Weight')
    tare_weight = fields.Float(string='Tare Wt.', digits='Stock Weight')
    net_weight = fields.Float(string='Net Wt.', digits='Stock Weight', compute='_compute_net_weight', store=True)

    @api.depends('gross_weight', 'tare_weight')
    def _compute_net_weight(self):
        for line in self:
            line.net_weight = max(line.gross_weight - line.tare_weight, 0.0)


class GatePassIn(models.Model):
    _name = 'combine.gate.pass.in'
    _description = 'Gate Pass Inward'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'combine.stores.print.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(default=lambda self: _('New'), readonly=True, copy=False)
    date = fields.Datetime(string='Gate In', default=fields.Datetime.now, required=True)
    partner_id = fields.Many2one('res.partner', string='Party', required=True, tracking=True)
    purchase_id = fields.Many2one('purchase.order', string='Purchase Order', tracking=True,
                                  domain="[('partner_id', 'child_of', partner_id), ('state', 'in', ('purchase', 'done'))]")
    party_ref = fields.Char(string='Party Invoice / DC Ref.', tracking=True)
    vehicle_no = fields.Char(string='Vehicle No.')
    driver = fields.Char()
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    state = fields.Selection([
        ('draft', 'Draft'), ('in', 'At Gate'), ('inspected', 'Inspected'), ('done', 'Received'), ('cancel', 'Cancelled'),
    ], default='draft', required=True, tracking=True, copy=False)
    line_ids = fields.One2many('combine.gate.pass.in.line', 'gate_pass_id', string='Items', copy=True)
    inspection_ids = fields.One2many('combine.inspection', 'gate_pass_id', string='Inspections')
    grn_ids = fields.One2many('combine.grn', 'gate_pass_id', string='GRNs')
    note = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('combine.gate.pass.in') or _('New')
        return super().create(vals_list)

    @api.onchange('purchase_id')
    def _onchange_purchase_id(self):
        if self.purchase_id:
            self.partner_id = self.purchase_id.partner_id
            self.line_ids = [(5, 0, 0)] + [(0, 0, vals) for vals in self._lines_from_purchase(self.purchase_id)]

    @api.model
    def _lines_from_purchase(self, order):
        return [{
            'product_id': pol.product_id.id,
            'purchase_line_id': pol.id,
            'uom_id': pol.product_uom_id.id,
            'qty_doc': pol.product_qty - pol.qty_received,
            'qty_received': pol.product_qty - pol.qty_received,
        } for pol in order.order_line.filtered(lambda l: l.product_id.type == 'consu' and l.product_qty > l.qty_received)]

    def action_gate_in(self):
        for gp in self:
            if not gp.line_ids:
                raise UserError(_('This gate pass has no items. Add the items that arrived with the quantity per party document and the quantity counted at the gate, then click Gate In.'))
            gp.state = 'in'
            if not gp.inspection_ids:
                self.env['combine.inspection'].create({
                    'gate_pass_id': gp.id,
                    'line_ids': [(0, 0, {'gate_line_id': l.id, 'qty_accepted': l.qty_received}) for l in gp.line_ids],
                })

    def action_cancel(self):
        if self.grn_ids.filtered(lambda g: g.state == 'done'):
            raise UserError(_('The goods of this gate pass are already received into stock through its GRN, so it cannot be changed. For a correction, return the goods to the vendor from the receipt.'))
        self.inspection_ids.write({'state': 'cancel'})
        self.write({'state': 'cancel'})

    def action_view_inspection(self):
        return self._open(self.inspection_ids, _('Inspection'))

    def action_view_grn(self):
        return self._open(self.grn_ids, _('GRN'))

    def _open(self, records, name):
        action = {'type': 'ir.actions.act_window', 'name': name, 'res_model': records._name}
        if len(records) == 1:
            action.update(view_mode='form', res_id=records.id)
        else:
            action.update(view_mode='list,form', domain=[('id', 'in', records.ids)])
        return action

    # print
    def _print_title(self):
        return 'Gate Pass Inward'

    def _print_info(self):
        return [('IGP No.', self.name), ('Gate In', fields.Datetime.context_timestamp(self, self.date).strftime('%d-%b-%y %H:%M')),
                ('Purchase Order', self.purchase_id.name or '-'), ('Party Inv / DC', self.party_ref or '-'),
                ('Vehicle No.', self.vehicle_no or '-'), ('Driver', self.driver or '-')]

    def _print_party(self):
        return self.partner_id

    def _print_columns(self):
        return [('Sr.', 'c'), ('Item', ''), ('Qty as per Party', 'n'), ('Qty at Gate', 'n'), ('UoM', 'c'),
                ('Packages', 'n'), ('Gross Wt.', 'n'), ('Tare Wt.', 'n'), ('Net Wt.', 'n')]

    def _print_rows(self):
        return [[i, l.product_id.display_name, num(l.qty_doc), num(l.qty_received), l.uom_id.name, l.packages or '-',
                 num(l.gross_weight), num(l.tare_weight), num(l.net_weight)] for i, l in enumerate(self.line_ids, 1)]

    def _print_totals(self):
        lines = self.line_ids
        return {2: num(sum(lines.mapped('qty_doc'))), 3: num(sum(lines.mapped('qty_received'))),
                5: sum(lines.mapped('packages')) or '-', 6: num(sum(lines.mapped('gross_weight'))),
                7: num(sum(lines.mapped('tare_weight'))), 8: num(sum(lines.mapped('net_weight')))}

    def _print_signatures(self):
        return ['Gate Officer', 'Driver', 'Store Incharge']


class GatePassInLine(models.Model):
    _name = 'combine.gate.pass.in.line'
    _description = 'Gate Pass Inward Line'
    _inherit = ['combine.gate.weight.mixin']

    gate_pass_id = fields.Many2one('combine.gate.pass.in', required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one('product.product', string='Item', required=True)
    purchase_line_id = fields.Many2one('purchase.order.line', string='PO Line')
    uom_id = fields.Many2one('uom.uom', string='UoM', compute='_compute_uom', store=True, readonly=False, precompute=True, required=True)
    qty_doc = fields.Float(string='Qty as per Party', digits='Product Unit')
    qty_received = fields.Float(string='Qty at Gate', digits='Product Unit')
    note = fields.Char(string='Remarks')

    @api.depends('product_id', 'purchase_line_id')
    def _compute_uom(self):
        for line in self:
            line.uom_id = line.uom_id or line.purchase_line_id.product_uom_id or line.product_id.uom_id
