from odoo import fields, models
from odoo.tools import SQL


class PurchaseReport(models.Model):
    _inherit = 'purchase.report'

    hs_code = fields.Char(string='HS Code', readonly=True)

    def _select(self) -> SQL:
        return SQL("%s, t.hs_code AS hs_code", super()._select())

    def _group_by(self) -> SQL:
        return SQL("%s, t.hs_code", super()._group_by())
