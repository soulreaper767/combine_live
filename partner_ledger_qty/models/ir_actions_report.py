from odoo import models


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        """Odoo's own invoice print refuses any selection containing a
        plain journal entry ("Only invoices could be printed."), which is
        what users hit printing JVs / bank / cash entries from the
        Journal Entries list. Print those selections as vouchers instead;
        invoice-only selections are untouched."""
        if res_ids and self._is_invoice_report(report_ref):
            ids = [res_ids] if isinstance(res_ids, int) else res_ids
            if any(m.move_type == 'entry' for m in self.env['account.move'].browse(ids)):
                return super()._render_qweb_pdf('partner_ledger_qty.action_report_voucher', ids, data)
        return super()._render_qweb_pdf(report_ref, res_ids=res_ids, data=data)
