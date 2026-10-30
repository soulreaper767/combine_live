from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    hs_code = fields.Char(
        string='HS Code', index='btree_not_null',
        help='Harmonized System / Pakistan Customs Tariff (PCT) code, e.g. 5205.1200. '
             'Printed on the Sales Tax Invoice and available in the Sales and Purchase reports.')
