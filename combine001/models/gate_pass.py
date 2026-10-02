from odoo import _, api, fields, models
from odoo.exceptions import UserError


class GatePass(models.Model):
    """BRD sec. 8: generated from a validated Delivery Challan
    (stock.picking, state='done'). Stock has already moved at that point
    (via the Delivery Challan itself) - the Gate Pass is purely a
    logistics/security exit document and never touches stock again (BRD
    sec. 8.2: 'Gate Pass should not create an additional stock
    deduction'), so this is a plain model with no stock.move of its own.
    """
    _name = 'combine001.gate.pass'
    _description = 'Gate Pass'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(default='New', copy=False, readonly=True)
    picking_id = fields.Many2one(
        'stock.picking', required=True, ondelete='restrict', string='Delivery Challan',
        domain="[('state', '=', 'done'), ('picking_type_code', '=', 'outgoing')]", tracking=True)
    sale_order_id = fields.Many2one(related='picking_id.sale_id', store=True, string='Contract / Delivery Order')
    partner_id = fields.Many2one(related='picking_id.partner_id', store=True, string='Customer')
    x_gst_status = fields.Selection(related='partner_id.x_gst_status', store=True, string='GST Status')
    x_income_tax_status = fields.Selection(related='partner_id.x_income_tax_status', store=True, string='Income Tax Status')
    x_pra_status = fields.Selection(related='partner_id.x_pra_status', store=True, string='PRA Status')
    x_show_pra_status = fields.Boolean(compute='_compute_x_show_pra_status')
    date = fields.Datetime(default=fields.Datetime.now)
    company_id = fields.Many2one(related='picking_id.company_id', store=True)
    line_ids = fields.One2many('combine001.gate.pass.line', 'gate_pass_id', string='Lines')

    _picking_uniq = models.Constraint(
        'UNIQUE(picking_id)',
        'A Gate Pass already exists for this Delivery Challan.',
    )

    @api.depends('line_ids.product_id.x_pra_applicable')
    def _compute_x_show_pra_status(self):
        for rec in self:
            rec.x_show_pra_status = bool(rec.line_ids.product_id.filtered('x_pra_applicable'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('combine001.gate.pass') or 'New'
            if vals.get('picking_id') and not vals.get('line_ids'):
                picking = self.env['stock.picking'].browse(vals['picking_id'])
                if picking.state != 'done':
                    raise UserError(_('A Gate Pass can only be created from a validated (done) Delivery Challan.'))
                vals['line_ids'] = [(0, 0, {
                    'move_id': move.id,
                }) for move in picking.move_ids.filtered(lambda m: m.state == 'done' and m.product_id)]
        return super().create(vals_list)


class GatePassLine(models.Model):
    _name = 'combine001.gate.pass.line'
    _description = 'Gate Pass Line'

    gate_pass_id = fields.Many2one('combine001.gate.pass', required=True, ondelete='cascade')
    move_id = fields.Many2one('stock.move', required=True, ondelete='restrict', string='Stock Move')
    product_id = fields.Many2one(related='move_id.product_id', store=True)
    quantity = fields.Float(related='move_id.quantity', store=True, string='Quantity Delivered')
    product_uom = fields.Many2one(related='move_id.product_uom', store=True, string='UoM')
    x_contract_price = fields.Float(related='move_id.sale_line_id.price_unit', store=True, string='Contract Price')
