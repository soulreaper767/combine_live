from odoo import models
from odoo.tools import SQL

ZERO = 0.005

MODES = {
    # account type, invoice type, credit-note type, sign (vendors shown as
    # positive amounts owed), picking type for the "last delivery" date
    'customer': {'account_type': 'asset_receivable', 'invoice': 'out_invoice',
                 'refund': 'out_refund', 'sign': 1, 'picking': 'outgoing'},
    'vendor': {'account_type': 'liability_payable', 'invoice': 'in_invoice',
               'refund': 'in_refund', 'sign': -1, 'picking': 'incoming'},
}


class PartyOutstandingReport(models.AbstractModel):
    """Party Outstanding Report - one line per customer (or vendor):
    Opening, Gross Sales/Purchases, Net (after credit notes),
    Receipts/Payments, Others, Closing, plus last delivery and last
    invoice dates.

    Every amount is read from the party's own receivable (or payable)
    journal items, split by what produced them, so the columns always
    reconcile exactly with the books:
        Closing = Opening + Net - Receipts/Payments + Others
    - Gross: invoices/bills (tax included - what the party owes)
    - Net: Gross less credit notes
    - Receipts/Payments: lines from registered payments or posted in a
      bank/cash journal
    - Others: everything else on the party's account (journal entries,
      write-offs, adjustments)
    Vendor figures are shown with the sign flipped, so an amount owed
    to a vendor is positive, same as an amount owed by a customer."""
    _name = 'report.partner_ledger_qty.party_outstanding_document'
    _description = 'Party Outstanding Report document'

    def _get_report_values(self, docids, data=None):
        stmt = self.env['report.partner_ledger_qty.partner_statement_document']
        return {
            'doc_ids': docids,
            'doc_model': 'party.outstanding.wizard',
            'docs': self.env['party.outstanding.wizard'].browse(docids),
            'get_po_data': self._get_po_data,
            'fmt_amount': stmt._fmt_amount,
        }

    def _get_po_data(self, wizard):
        company = self.env.company
        mode = MODES[wizard.party_type]
        date_from, date_to = wizard.date_from, wizard.date_to

        # raw SQL below: push pending ORM writes first, as Odoo's own reports do
        self.env.flush_all()
        self.env.cr.execute(SQL(
            """
            SELECT p.commercial_partner_id AS partner_id,
                   SUM(CASE WHEN aml.date < %(date_from)s THEN aml.balance ELSE 0 END) AS opening,
                   SUM(CASE WHEN aml.date >= %(date_from)s AND am.move_type = %(inv)s
                            THEN aml.balance ELSE 0 END) AS gross,
                   SUM(CASE WHEN aml.date >= %(date_from)s AND am.move_type = %(ref)s
                            THEN aml.balance ELSE 0 END) AS refunds,
                   SUM(CASE WHEN aml.date >= %(date_from)s
                             AND am.move_type NOT IN (%(inv)s, %(ref)s)
                             AND (aml.payment_id IS NOT NULL OR j.type IN ('bank', 'cash'))
                            THEN aml.balance ELSE 0 END) AS settled,
                   SUM(CASE WHEN aml.date >= %(date_from)s
                             AND am.move_type NOT IN (%(inv)s, %(ref)s)
                             AND aml.payment_id IS NULL AND j.type NOT IN ('bank', 'cash')
                            THEN aml.balance ELSE 0 END) AS others
            FROM account_move_line aml
            JOIN account_move am ON am.id = aml.move_id
            JOIN account_journal j ON j.id = aml.journal_id
            JOIN account_account acc ON acc.id = aml.account_id
            JOIN res_partner p ON p.id = aml.partner_id
            WHERE aml.parent_state = 'posted'
              AND aml.company_id = %(company_id)s
              AND acc.account_type = %(account_type)s
              AND aml.date <= %(date_to)s
            GROUP BY p.commercial_partner_id
            """,
            date_from=date_from, date_to=date_to, company_id=company.id,
            inv=mode['invoice'], ref=mode['refund'], account_type=mode['account_type'],
        ))
        sums = {r['partner_id']: r for r in self.env.cr.dictfetchall()}

        partners = self.env['res.partner'].browse(list(sums))
        if wizard.category_ids:
            partners = partners.filtered(lambda p: p.category_id & wizard.category_ids)

        last_inv = self._last_dates(SQL(
            """
            SELECT am.commercial_partner_id, MAX(am.invoice_date)
            FROM account_move am
            WHERE am.state = 'posted' AND am.move_type = %(inv)s
              AND am.company_id = %(company_id)s AND am.invoice_date <= %(date_to)s
            GROUP BY am.commercial_partner_id
            """, inv=mode['invoice'], company_id=company.id, date_to=date_to))
        last_dlv = {}
        if 'stock.picking' in self.env:   # only when the Inventory app is installed
            last_dlv = self._last_dates(SQL(
                """
                SELECT p.commercial_partner_id, MAX(sp.date_done)::date
                FROM stock_picking sp
                JOIN stock_picking_type spt ON spt.id = sp.picking_type_id
                JOIN res_partner p ON p.id = sp.partner_id
                WHERE sp.state = 'done' AND spt.code = %(code)s
                  AND sp.company_id = %(company_id)s AND sp.date_done::date <= %(date_to)s
                GROUP BY p.commercial_partner_id
                """, code=mode['picking'], company_id=company.id, date_to=date_to))

        sign = mode['sign']
        rows = []
        for partner in partners.sorted(lambda p: (p.name or '').lower()):
            s = sums[partner.id]
            opening = sign * s['opening']
            gross = sign * s['gross']
            net = gross + sign * s['refunds']
            settled = -sign * s['settled']
            others = sign * s['others']
            closing = opening + net - settled + others
            if wizard.hide_zero and all(abs(v) < ZERO for v in (opening, gross, net, settled, others, closing)):
                continue
            rows.append({
                'partner': partner.name,
                'last_dlv': last_dlv.get(partner.id),
                'last_inv': last_inv.get(partner.id),
                'opening': opening, 'gross': gross, 'net': net,
                'settled': settled, 'others': others, 'closing': closing,
            })
        for i, row in enumerate(rows, start=1):
            row['sr'] = i

        totals = {k: sum(r[k] for r in rows) for k in ('opening', 'gross', 'net', 'settled', 'others', 'closing')}
        is_customer = wizard.party_type == 'customer'
        return {
            'company': company,
            'date_from': date_from,
            'date_to': date_to,
            'title': 'Party Outstanding - %s' % ('Customers' if is_customer else 'Vendors'),
            'categories': ', '.join(wizard.category_ids.mapped('name')),
            'labels': {
                'dlv': 'Last Dlv Date' if is_customer else 'Last Rcpt Date',
                'gross': 'Gross Sales' if is_customer else 'Gross Purchases',
                'net': 'Net Sales' if is_customer else 'Net Purchases',
                'settled': 'Receipts' if is_customer else 'Payments',
            },
            'rows': rows,
            'totals': totals,
        }

    def _last_dates(self, query):
        self.env.cr.execute(query)
        return dict(self.env.cr.fetchall())
