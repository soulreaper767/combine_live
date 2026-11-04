from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ConversionReceive(models.TransientModel):
    _name = 'combine.conversion.receive'
    _description = 'Receive Converted Goods'

    order_id = fields.Many2one('combine.conversion.order', required=True)
    output_product_id = fields.Many2one(related='order_id.output_product_id')
    output_uom_id = fields.Many2one(related='order_id.output_uom_id')
    waste_product_id = fields.Many2one(related='order_id.waste_product_id')
    date = fields.Date(required=True, default=fields.Date.context_today)
    packages = fields.Integer(string='No. of Packages')
    weight_per_package = fields.Float(string='Weight / Package', digits='Stock Weight')
    qty = fields.Float(string='Qty Received', digits='Product Unit',
                       compute='_compute_qty', store=True, readonly=False)
    waste_qty = fields.Float(string='Waste Returned', digits='Product Unit')
    note = fields.Char()

    @api.depends('packages', 'weight_per_package')
    def _compute_qty(self):
        for wiz in self:
            wiz.qty = wiz.packages * wiz.weight_per_package if wiz.packages and wiz.weight_per_package else wiz.qty

    def action_receive(self):
        self.ensure_one()
        if self.qty <= 0 and self.waste_qty <= 0:
            raise UserError(_('Enter the quantity received.'))
        self.order_id._receive(self.qty, waste_qty=self.waste_qty, date=self.date, packages=self.packages,
                               weight_per_package=self.weight_per_package, note=self.note)
        return {'type': 'ir.actions.act_window_close'}
