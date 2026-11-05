from odoo import api, models

# Odoo's own document formats -> the house-style format for the same document.
# Every route that renders one of the left (Print menu, Send / email
# attachments, portal download, preview) gets the right one instead, so no
# document ever comes out in another layout.
HOUSE_STYLE = {
    'account.report_invoice_with_payments': 'partner_ledger_qty.report_fbr_invoice',
    'account.report_invoice': 'partner_ledger_qty.report_fbr_invoice',
    'account.report_payment_receipt': 'partner_ledger_qty.report_payment_voucher',
    'sale.report_saleorder': 'partner_ledger_qty.report_sale_order',
    'sale.report_saleorder_pro_forma': 'partner_ledger_qty.report_sale_order',
    'sale.report_saleorder_raw': 'partner_ledger_qty.report_sale_order',
    'purchase.report_purchaseorder': 'partner_ledger_qty.report_purchase_order',
    'purchase.report_purchasequotation': 'partner_ledger_qty.report_purchase_order',
    'stock.report_deliveryslip': 'partner_ledger_qty.report_picking',
}
# their Print-menu entries, hidden so each document has one print of its own
HIDDEN_PRINTS = (
    'account.account_invoices', 'account.account_invoices_without_payment', 'account.action_report_payment_receipt',
    'sale.action_report_saleorder', 'sale.action_report_pro_forma_invoice', 'sale_pdf_quote_builder.action_report_saleorder_raw',
    'purchase.action_report_purchase_order', 'purchase.report_purchase_quotation', 'stock.action_report_delivery',
)


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def _house_style_ref(self, report_ref):
        if self.env.context.get('combine_odoo_layout'):
            return report_ref
        try:
            report = self._get_report(report_ref)
        except Exception:
            return report_ref
        target = HOUSE_STYLE.get(report.report_name)
        if target and self.sudo().search_count([('report_name', '=', target), ('model', '=', report.model)]):
            return target
        return report_ref

    def _pre_render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        return super()._pre_render_qweb_pdf(self._house_style_ref(report_ref), res_ids=res_ids, data=data)

    def _render_qweb_html(self, report_ref, docids, data=None):
        return super()._render_qweb_html(self._house_style_ref(report_ref), docids, data=data)

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


class IrActionsActions(models.Model):
    _inherit = 'ir.actions.actions'

    @api.model
    def _get_bindings(self, model_name):
        result = super()._get_bindings(model_name)
        reports = result.get('report')
        if not reports:
            return result
        hidden = {rec.id for rec in (self.env.ref(x, raise_if_not_found=False) for x in HIDDEN_PRINTS) if rec}
        if not hidden & {r['id'] for r in reports}:
            return result
        out = dict(result)
        out['report'] = tuple(r for r in reports if r['id'] not in hidden)
        return type(result)(out)
