from collections import defaultdict

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError


class DemandPoWizard(models.TransientModel):
    _name = 'combine.demand.po.wizard'
    _description = 'Create Purchase Orders from Demand Notes'

    line_ids = fields.One2many('combine.demand.po.wizard.line', 'wizard_id', string='Items')

    def action_create(self):
        self.ensure_one()
        lines = self.line_ids.filtered(lambda l: l.qty > 0)
        if not lines:
            raise UserError(_('Every line has zero quantity. Enter the quantity to order on the lines (or remove the lines not to order), then click Create.'))
        missing = lines.filtered(lambda l: not l.vendor_id)
        if missing:
            raise UserError(_('Choose a vendor on each line - missing for: %s. One purchase order is made per vendor.', ', '.join(missing.product_id.mapped('display_name'))))
        by_vendor = defaultdict(lambda: self.env['combine.demand.po.wizard.line'])
        for line in lines:
            by_vendor[line.vendor_id] |= line
        orders = self.env['purchase.order']
        for vendor, vlines in by_vendor.items():
            orders |= self.env['purchase.order'].create({
                'partner_id': vendor.id,
                'origin': ', '.join(sorted(set(vlines.demand_line_id.demand_id.mapped('name')))),
                'order_line': [Command.create({
                    'product_id': l.product_id.id,
                    'product_qty': l.qty,
                    'product_uom_id': l.uom_id.id,
                    'price_unit': l.price_unit,
                    'x_demand_line_id': l.demand_line_id.id,
                }) for l in vlines],
            })
        return {
            'type': 'ir.actions.act_window', 'name': _('Purchase Orders'), 'res_model': 'purchase.order',
            'view_mode': 'list,form' if len(orders) > 1 else 'form',
            'domain': [('id', 'in', orders.ids)], 'res_id': orders.id if len(orders) == 1 else False,
        }


class DemandPoWizardLine(models.TransientModel):
    _name = 'combine.demand.po.wizard.line'
    _description = 'Create Purchase Orders - line'

    wizard_id = fields.Many2one('combine.demand.po.wizard', required=True, ondelete='cascade')
    demand_line_id = fields.Many2one('combine.demand.note.line', required=True, readonly=True)
    demand_id = fields.Many2one(related='demand_line_id.demand_id', string='Demand Note')
    demand_qty = fields.Float(related='demand_line_id.pending_qty', string='Pending')
    product_id = fields.Many2one('product.product', string='Item', required=True, readonly=True)
    qty = fields.Float(string='Order Qty', digits='Product Unit')
    uom_id = fields.Many2one('uom.uom', string='UoM', required=True)
    vendor_id = fields.Many2one('res.partner', string='Vendor')
    price_unit = fields.Float(string='Rate', digits='Product Price')

    @api.onchange('vendor_id', 'qty')
    def _onchange_vendor(self):
        if self.vendor_id and self.product_id:
            seller = self.product_id._select_seller(partner_id=self.vendor_id, quantity=self.qty or 1.0)
            if seller:
                self.price_unit = seller.price
