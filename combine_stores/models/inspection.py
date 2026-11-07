from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare

from .stores_print import num


class Inspection(models.Model):
    _name = 'combine.inspection'
    _description = 'Quality Inspection'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'combine.stores.print.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(default=lambda self: _('New'), readonly=True, copy=False)
    gate_pass_id = fields.Many2one('combine.gate.pass.in', string='Gate Pass Inward', required=True, ondelete='cascade')
    partner_id = fields.Many2one(related='gate_pass_id.partner_id', store=True, string='Party')
    purchase_id = fields.Many2one(related='gate_pass_id.purchase_id', store=True)
    date = fields.Date(default=fields.Date.context_today, required=True)
    inspector_id = fields.Many2one('res.users', string='Inspected By', default=lambda self: self.env.user)
    rejection_action = fields.Selection([
        ('replace', 'Vendor to replace (purchase order stays open)'),
        ('cancel', 'Cancel rejected quantity from the purchase order'),
    ], default='replace', required=True, string='Rejected Goods')
    state = fields.Selection([('draft', 'Draft'), ('done', 'Done'), ('cancel', 'Cancelled')],
                             default='draft', required=True, tracking=True, copy=False)
    line_ids = fields.One2many('combine.inspection.line', 'inspection_id', string='Items')
    grn_ids = fields.One2many('combine.grn', 'inspection_id', string='GRN')
    gate_out_ids = fields.One2many('combine.gate.pass.out', 'inspection_id', string='Rejection Gate Passes')
    has_rejection = fields.Boolean(compute='_compute_has_rejection')
    note = fields.Text()

    @api.depends('line_ids.qty_rejected')
    def _compute_has_rejection(self):
        for ins in self:
            ins.has_rejection = any(l.qty_rejected > 0 for l in ins.line_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('combine.inspection') or _('New')
        return super().create(vals_list)

    def action_done(self):
        for ins in self:
            if ins.state != 'draft':
                continue
            for line in ins.line_ids:
                rounding = line.uom_id.rounding or 0.01
                if float_compare(line.qty_accepted, 0.0, precision_rounding=rounding) < 0 or \
                        float_compare(line.qty_accepted, line.qty_received, precision_rounding=rounding) > 0:
                    raise UserError(_('%s: the accepted quantity must be between 0 and the quantity received at the gate. Correct the accepted quantity on the line.', line.product_id.display_name))
                if line.qty_rejected > 0 and not line.reason:
                    raise UserError(_('%s: part of the quantity is rejected - enter the reason on the line (e.g. damaged, wet, wrong count) before completing the inspection.', line.product_id.display_name))
            ins.state = 'done'
            ins.gate_pass_id.state = 'inspected'
            accepted = ins.line_ids.filtered(lambda l: l.qty_accepted > 0)
            if accepted:
                self.env['combine.grn'].create({
                    'inspection_id': ins.id,
                    'gate_pass_id': ins.gate_pass_id.id,
                    'line_ids': [(0, 0, {
                        'product_id': l.product_id.id,
                        'purchase_line_id': l.gate_line_id.purchase_line_id.id,
                        'uom_id': l.uom_id.id,
                        'qty': l.qty_accepted,
                        'net_weight': l.gate_line_id.net_weight * (l.qty_accepted / l.qty_received) if l.qty_received else 0.0,
                    }) for l in accepted],
                })
        return True

    def action_gate_out_rejected(self):
        self.ensure_one()
        rejected = self.line_ids.filtered(lambda l: l.qty_rejected > 0)
        if not rejected:
            raise UserError(_('Nothing was rejected on this inspection, so there are no goods to send back to the vendor.'))
        gate_out = self.env['combine.gate.pass.out'].create({
            'pass_type': 'purchase_return',
            'partner_id': self.partner_id.id,
            'inspection_id': self.id,
            'reference': self.gate_pass_id.party_ref or self.gate_pass_id.name,
            'line_ids': [(0, 0, {'product_id': l.product_id.id, 'uom_id': l.uom_id.id, 'qty': l.qty_rejected,
                                 'note': l.reason}) for l in rejected],
        })
        return {'type': 'ir.actions.act_window', 'res_model': gate_out._name, 'res_id': gate_out.id, 'view_mode': 'form'}

    def action_view_grn(self):
        return self.gate_pass_id._open(self.grn_ids, _('GRN'))

    # print
    def _print_title(self):
        return 'Quality Inspection Report'

    def _print_info(self):
        return [('Inspection No.', self.name), ('Date', self._print_date(self.date)),
                ('Gate Pass', self.gate_pass_id.name), ('Purchase Order', self.purchase_id.name or '-'),
                ('Inspected By', self.inspector_id.name or '-'), ('Rejected Goods', dict(self._fields['rejection_action'].selection)[self.rejection_action])]

    def _print_party(self):
        return self.partner_id

    def _print_columns(self):
        return [('Sr.', 'c'), ('Item', ''), ('Received', 'n'), ('Accepted', 'n'), ('Rejected', 'n'), ('UoM', 'c'), ('Reason / Remarks', '')]

    def _print_rows(self):
        return [[i, l.product_id.display_name, num(l.qty_received), num(l.qty_accepted), num(l.qty_rejected), l.uom_id.name, l.reason or '']
                for i, l in enumerate(self.line_ids, 1)]

    def _print_totals(self):
        lines = self.line_ids
        return {2: num(sum(lines.mapped('qty_received'))), 3: num(sum(lines.mapped('qty_accepted'))), 4: num(sum(lines.mapped('qty_rejected')))}

    def _print_signatures(self):
        return ['Quality Inspector', 'Store Incharge', 'Approved by']


class InspectionLine(models.Model):
    _name = 'combine.inspection.line'
    _description = 'Quality Inspection Line'

    inspection_id = fields.Many2one('combine.inspection', required=True, ondelete='cascade', index=True)
    gate_line_id = fields.Many2one('combine.gate.pass.in.line', required=True, ondelete='cascade')
    product_id = fields.Many2one(related='gate_line_id.product_id', store=True)
    uom_id = fields.Many2one(related='gate_line_id.uom_id', store=True)
    qty_received = fields.Float(related='gate_line_id.qty_received', store=True, string='Received')
    qty_accepted = fields.Float(string='Accepted', digits='Product Unit')
    qty_rejected = fields.Float(string='Rejected', digits='Product Unit', compute='_compute_rejected', store=True)
    reason = fields.Char(string='Reason / Remarks')

    @api.depends('qty_received', 'qty_accepted')
    def _compute_rejected(self):
        for line in self:
            line.qty_rejected = max(line.qty_received - line.qty_accepted, 0.0)
