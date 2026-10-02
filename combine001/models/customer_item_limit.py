from odoo import fields, models


class CustomerItemLimit(models.Model):
    _name = 'combine001.customer.item.limit'
    _description = 'Customer-wise Item Quantity Limit'
    _rec_name = 'product_id'

    partner_id = fields.Many2one('res.partner', required=True, string='Customer', ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True, string='Product', ondelete='cascade')
    max_qty = fields.Float(required=True, string='Maximum Quantity')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    _partner_product_uniq = models.Constraint(
        'UNIQUE(partner_id, product_id, company_id)',
        'A quantity limit already exists for this Customer + Product combination.',
    )
