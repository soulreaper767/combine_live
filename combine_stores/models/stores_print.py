from odoo import fields, models
from odoo.tools import float_is_zero


def num(value, digits=2):
    if value is None or value is False:
        return ''
    if float_is_zero(value, precision_digits=digits):
        return '-'
    return f'{value:,.{digits}f}'


class StoresPrintMixin(models.AbstractModel):
    """Every stores document prints through one template (report/stores_reports.xml):
    a title, info pairs, a party box, a line table with totals and signature boxes."""
    _name = 'combine.stores.print.mixin'
    _description = 'Stores document print'

    def _print_title(self):
        return self._description

    def _print_info(self):
        return []

    def _print_party(self):
        return False

    def _print_columns(self):
        return []

    def _print_rows(self):
        return []

    def _print_totals(self):
        return {}

    def _print_signatures(self):
        return ['Prepared by', 'Checked by', 'Approved by']

    def _print_note(self):
        return self.note if 'note' in self._fields else False

    def _print_date(self, value):
        return fields.Date.to_string(fields.Date.to_date(value)) if value else ''
