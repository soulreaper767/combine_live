from odoo import models
from odoo.tools import SQL

INVOICE_MOVE_TYPES = ('out_invoice', 'out_refund', 'in_invoice', 'in_refund')
AGE_MOVE_TYPES = ('out_invoice', 'in_invoice')
DEBIT_MOVE_TYPES = ('out_invoice', 'in_refund')
CREDIT_MOVE_TYPES = ('out_refund', 'in_invoice')


class PartnerStatementReport(models.AbstractModel):
    """Data source for the itemized Partner Statement PDF.

    Deliberately a brand-new, self-contained report rather than a
    reskin of the native Partner Ledger: that report's PDF/XLSX export
    is rendered through account_reports' own generic template, shared
    by every report built on that engine (Trial Balance, General
    Ledger, ...) - there is no per-report override of columns or
    header layout in that shared template. See the module description
    for the full reasoning.

    Two kinds of rows, one per voucher/line, ordered by date:
    - Invoice/bill ITEM lines (one row per product line, not per
      invoice) - carries the full pricing/tax breakdown (gross rate,
      discount, net rate, ex./incl. amount, GST) plus Debit/Credit for
      that one line. A 5-line invoice becomes 5 rows here, each
      advancing the running balance by its own share - deliberately
      itemized, this is not the native report's one-row-per-invoice
      shape.
    - Everything else (payments, misc journal entries) - one row per
      voucher, pricing/item columns blank, Debit/Credit from that
      line's own value, same as a conventional ledger line.
    """
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
        self.env.cr.execute(SQL(
            """
            WITH item_lines AS (
                SELECT
                    aml.id,
                    am.date AS voucher_date,
                    am.name AS voucher_no,
                    COALESCE(am.ref, am.name) AS remarks,
                    aml.name AS item_name,
                    CASE WHEN am.move_type IN %(age_move_types)s
                         THEN (%(date_to)s - COALESCE(am.invoice_date, am.date))
                         ELSE NULL END AS invoice_age,
                    aml.price_unit AS gross_rate,
                    aml.quantity AS quantity,
                    aml.discount AS discount,
                    aml.price_unit * (1 - COALESCE(aml.discount, 0) / 100.0) AS net_rate,
                    aml.price_subtotal AS ex_amount,
                    COALESCE((
                        SELECT SUM(t.amount) FROM account_move_line_account_tax_rel rel
                        JOIN account_tax t ON t.id = rel.account_tax_id
                        WHERE rel.account_move_line_id = aml.id
                    ), 0) AS gst_rate,
                    (aml.price_total - aml.price_subtotal) AS gst_amount,
                    aml.price_total AS incl_amount,
                    CASE WHEN am.move_type IN %(debit_move_types)s THEN aml.price_total ELSE 0 END AS debit,
                    CASE WHEN am.move_type IN %(credit_move_types)s THEN aml.price_total ELSE 0 END AS credit
                FROM account_move_line aml
                JOIN account_move am ON am.id = aml.move_id
                WHERE am.partner_id = %(partner_id)s
                  AND aml.display_type = 'product'
                  AND am.move_type IN %(invoice_move_types)s
                  AND am.state = 'posted'
                  AND am.date BETWEEN %(date_from)s AND %(date_to)s
            ),
            ledger_lines AS (
                SELECT
                    aml.id,
                    aml.date AS voucher_date,
                    am.name AS voucher_no,
                    COALESCE(aml.name, am.ref, am.name) AS remarks,
                    NULL::text AS item_name,
                    NULL::integer AS invoice_age,
                    NULL::double precision AS gross_rate,
                    NULL::double precision AS quantity,
                    NULL::double precision AS discount,
                    NULL::double precision AS net_rate,
                    NULL::numeric AS ex_amount,
                    NULL::double precision AS gst_rate,
                    NULL::numeric AS gst_amount,
                    NULL::numeric AS incl_amount,
                    aml.debit AS debit,
                    aml.credit AS credit
                FROM account_move_line aml
                JOIN account_account acc ON acc.id = aml.account_id
                JOIN account_move am ON am.id = aml.move_id
                WHERE aml.partner_id = %(partner_id)s
                  AND acc.account_type IN %(account_types)s
                  AND am.state = 'posted'
                  AND aml.date BETWEEN %(date_from)s AND %(date_to)s
                  AND (am.move_type IS NULL OR am.move_type NOT IN %(invoice_move_types)s)
            )
            SELECT * FROM item_lines
            UNION ALL
            SELECT * FROM ledger_lines
            ORDER BY voucher_date, id
            """,
            partner_id=partner.id, account_types=account_types,
            invoice_move_types=INVOICE_MOVE_TYPES, age_move_types=AGE_MOVE_TYPES,
            debit_move_types=DEBIT_MOVE_TYPES, credit_move_types=CREDIT_MOVE_TYPES,
            date_from=date_from, date_to=date_to,
        ))
        return self.env.cr.dictfetchall()
