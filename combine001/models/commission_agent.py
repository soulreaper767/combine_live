from odoo import fields, models

COMMISSION_BASE_SELECTION = [
    ('sales_value', 'Sales Value'),
    ('product_value', 'Product Value'),
    ('quantity', 'Quantity'),
    ('net_sales_value', 'Net Sales Value'),
]


class CommissionAgent(models.Model):
    _name = 'combine001.commission.agent'
    _description = 'Commission Agent'

    name = fields.Char(required=True)
    partner_id = fields.Many2one('res.partner', string='Related Partner')
    default_rate = fields.Float(string='Default Commission Rate (%)')
    default_base = fields.Selection(
        COMMISSION_BASE_SELECTION, default='sales_value', required=True,
        string='Default Commission Base',
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
