from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    x_delivery_challan_id = fields.Many2one(
        'stock.picking', string='Delivery Challan', readonly=True, copy=False,
        index='btree_not_null', ondelete='set null')
