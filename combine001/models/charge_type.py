from odoo import fields, models


class ChargeType(models.Model):
    _name = 'combine001.charge.type'
    _description = 'Additional Charge Type'

    name = fields.Char(required=True)
    computation = fields.Selection([
        ('fixed', 'Fixed Amount'),
        ('percentage', 'Percentage of Untaxed Total'),
    ], default='fixed', required=True)
    default_amount = fields.Float(string='Default Amount / Percentage')
    product_id = fields.Many2one(
        'product.product', required=True, string='Charge Product',
        help='Service product used to represent this charge as a Sales Order '
             'line; its Income Account and Taxes drive the accounting/tax '
             'treatment of the charge (BRD req. CHG-003).',
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
