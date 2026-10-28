from odoo import models
from odoo.tools import SQL


class PartnerStatementReport(models.AbstractModel):
    """Data source for the corporate-formatted Partner Statement PDF.

    Deliberately a brand-new, self-contained report rather than a
    reskin of the native Partner Ledger: that report's PDF/XLSX export
    is rendered through account_reports' own generic template, shared
    by every report built on that engine (Trial Balance, General
    Ledger, ...) - there is no per-report override of columns, header
    layout or currency display in that shared template, only of what
    data feeds the (fixed) column/row structure. Getting a different
    column set, a company-left/partner-right letterhead and a single
    "amounts in X" line instead of a currency symbol on every cell
    needs its own template, so it needs its own report and its own
    (much simpler) query - it does not reuse the Partner Ledger's
    handler at all, it reads account.move.line directly.

    Scope matches the Partner Ledger for the same partner: journal
    items on that partner's own receivable/payable account(s), posted
    only (a statement sent to a customer/vendor shouldn't show drafts).
    An opening balance line covers everything before the date range."""
    _name = 'report.partner_ledger_qty.partner_statement_document'
    _description = 'Partner Statement document'

    def _get_report_values(self, docids, data=None):
        wizard = self.env['partner.ledger.statement.wizard'].browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'partner.ledger.statement.wizard',
            'docs': wizard,
            'get_statement_data': self._get_statement_data,
        }

    def _get_statement_data(self, wizard):
        partner = wizard.partner_id
        company = self.env.company
        account_types = ('asset_receivable', 'liability_payable')

        opening_balance = self._get_opening_balance(partner, account_types, wizard.date_from)
        rows = self._get_lines(partner, account_types, wizard.date_from, wizard.date_to)

        running = opening_balance
        total_debit = total_credit = 0.0
        for row in rows:
            running += row['debit'] - row['credit']
            row['running_balance'] = running
            total_debit += row['debit']
            total_credit += row['credit']

        return {
            'company': company,
            'partner': partner,
            'currency': company.currency_id,
            'date_from': wizard.date_from,
            'date_to': wizard.date_to,
            'opening_balance': opening_balance,
            'rows': rows,
            'total_debit': total_debit,
            'total_credit': total_credit,
            'closing_balance': running,
        }

    def _get_opening_balance(self, partner, account_types, date_from):
        self.env.cr.execute(SQL(
            """
            SELECT COALESCE(SUM(aml.balance), 0)
            FROM account_move_line aml
            JOIN account_account acc ON acc.id = aml.account_id
            JOIN account_move am ON am.id = aml.move_id
            WHERE aml.partner_id = %(partner_id)s
              AND acc.account_type IN %(account_types)s
              AND am.state = 'posted'
              AND aml.date < %(date_from)s
            """,
            partner_id=partner.id, account_types=account_types, date_from=date_from,
        ))
        return self.env.cr.fetchone()[0] or 0.0

    def _get_lines(self, partner, account_types, date_from, date_to):
        # remarks: same issue as quantity - the row shown is the
        # receivable/payable line, whose own name is usually blank for an
        # invoice (the description lives on the product lines instead).
        # Falls back to the invoice's own reference, then its number.
        self.env.cr.execute(SQL(
            """
            SELECT
                aml.id,
                aml.date,
                COALESCE(aml.invoice_date, aml.date) AS invoice_date,
                COALESCE(aml.name, am.ref, am.name) AS remarks,
                aml.debit,
                aml.credit,
                am.name AS move_name,
                am.ref AS move_ref,
                j.code AS journal_code,
                CASE WHEN am.move_type = 'out_invoice' THEN (
                    SELECT SUM(aml_qty.quantity) FROM account_move_line aml_qty
                    WHERE aml_qty.move_id = aml.move_id
                      AND aml_qty.display_type = 'product'
                ) ELSE NULL END AS quantity
            FROM account_move_line aml
            JOIN account_account acc ON acc.id = aml.account_id
            JOIN account_move am ON am.id = aml.move_id
            JOIN account_journal j ON j.id = aml.journal_id
            WHERE aml.partner_id = %(partner_id)s
              AND acc.account_type IN %(account_types)s
              AND am.state = 'posted'
              AND aml.date BETWEEN %(date_from)s AND %(date_to)s
            ORDER BY aml.date, aml.id
            """,
            partner_id=partner.id, account_types=account_types,
            date_from=date_from, date_to=date_to,
        ))
        return self.env.cr.dictfetchall()
