from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    x_max_order_qty = fields.Float(
        string='Max Order Quantity',
        help='Maximum quantity allowed on a single Sales Order line for this '
             'product (BRD req. QC-001). Leave at 0 for no limit.',
    )

    x_pra_applicable = fields.Boolean(
        string='PRA Applicable (Service)',
        help='Punjab Revenue Authority services sales tax applies to this '
             'product. Most of this business is goods (GST), not services '
             '(PRA) - a document only shows the customer/vendor\'s PRA '
             'status when at least one of its lines has this flag set.',
    )
