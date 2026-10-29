from odoo import models
from odoo.tools import SQL


class AccountPartnerLedgerReportHandler(models.AbstractModel):
    """Adds a 'Qty' column to the native Partner Ledger report, showing
    the invoiced quantity on Sales Invoice lines only - blank for every
    other line type (bills, payments, misc entries, credit notes).

    The row the Partner Ledger shows for an invoice is its receivable/
    payable line (the balancing entry against the partner's control
    account) - account_move_line.quantity on THAT line is always 0,
    Odoo never puts a meaningful quantity there. The real quantity lives
    on the invoice's own product lines (display_type='product'), a
    different account_move_line row on the same move - so the value
    here is the SUM of those sibling lines' quantities, not this row's
    own (always-zero) quantity. Confirmed by testing: an early version
    that read account_move_line.quantity directly showed 0 for every
    invoice.

    Uses account_reports' own documented extension hook
    (_get_additional_column_aml_values, see
    account_reports/models/account_partner_ledger.py - "This method is
    intended to be overridden by other modules to add custom fields to
    the partner ledger query") instead of touching the core report file
    or its XML - the base report, its other columns and every other
    report built on this engine are untouched."""
    _inherit = 'account.partner.ledger.report.handler'

    def _get_additional_column_aml_values(self):
        base = super()._get_additional_column_aml_values()
        return SQL(
            "%s CASE WHEN account_move.move_type = 'out_invoice' THEN ("
            "    SELECT SUM(aml_qty.quantity) FROM account_move_line aml_qty "
            "    WHERE aml_qty.move_id = account_move_line.move_id "
            "      AND aml_qty.display_type = 'product'"
            ") ELSE NULL END AS quantity,",
            base,
        )
