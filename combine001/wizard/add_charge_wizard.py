from odoo import api, fields, models


class AddChargeWizard(models.TransientModel):
    _name = 'combine001.add.charge.wizard'
    _description = 'Add Additional Charge to Sales Order'

    order_id = fields.Many2one('sale.order', required=True, default=lambda self: self.env.context.get('active_id'))
    charge_type_id = fields.Many2one('combine001.charge.type', required=True)
    amount = fields.Float(string='Amount / Percentage')

    @api.onchange('charge_type_id')
    def _onchange_charge_type_id(self):
        if self.charge_type_id:
            self.amount = self.charge_type_id.default_amount

    def action_add_charge(self):
        self.ensure_one()
        charge = self.charge_type_id
        order = self.order_id
        if charge.computation == 'percentage':
            base = sum(order.order_line.filtered(
                lambda l: not l.display_type and not l.x_is_charge_line
            ).mapped('price_subtotal'))
            price_unit = base * (self.amount / 100.0)
        else:
            price_unit = self.amount
        self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': charge.product_id.id,
            'name': charge.name,
            'product_uom_qty': 1,
            'price_unit': price_unit,
            'x_is_charge_line': True,
        })
        return {'type': 'ir.actions.act_window_close'}
