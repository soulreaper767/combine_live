from odoo import fields, models


class SaleReport(models.Model):
    _inherit = 'sale.report'

    hs_code = fields.Char(string='HS Code', readonly=True)

    def _select_additional_fields(self):
        res = super()._select_additional_fields()
        res['hs_code'] = 't.hs_code'
        return res

    def _group_by_sale(self):
        return super()._group_by_sale() + ',\n            t.hs_code'
