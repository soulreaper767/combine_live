from odoo import models
from odoo.tools import SQL

PARTY_ACCOUNT_TYPES = ('asset_receivable', 'liability_payable')
ZERO = 0.005


def _split(value):
    """Net figure -> (debit side, credit side)."""
    return (value, 0.0) if value > 0 else (0.0, -value)


class TrialBalancePartyReport(models.AbstractModel):
    """Trial Balance with Party: the native Trial Balance's figures
    (opening / period debit & credit / closing, per account), plus each
    customer's / vendor's own balance listed under its receivable /
    payable control account.

    Same opening-balance rule as Odoo's native report: balance-sheet
    accounts carry everything before the period forward; income/expense
    accounts (and the current-year-earnings account) only carry what
    happened since the start of the fiscal year, and everything from
    earlier fiscal years is shown on one "Undistributed Profits/Losses"
    line - so the totals balance exactly like the native one."""
    _name = 'report.partner_ledger_qty.trial_balance_party_document'
    _description = 'Trial Balance with Party document'

    def _get_report_values(self, docids, data=None):
        stmt = self.env['report.partner_ledger_qty.partner_statement_document']
        return {
            'doc_ids': docids,
            'doc_model': 'trial.balance.party.wizard',
            'docs': self.env['trial.balance.party.wizard'].browse(docids),
            'get_tb_data': self._get_tb_data,
            'fmt_amount': stmt._fmt_amount,
        }

    def _get_tb_data(self, wizard):
        company = self.env.company
        date_from, date_to = wizard.date_from, wizard.date_to
        fy_start = company.compute_fiscalyear_dates(date_from)['date_from']

        # raw SQL below: push any pending ORM writes to the database first,
        # as Odoo's own reports do, or just-posted entries can be missed
        self.env.flush_all()
        self.env.cr.execute(SQL(
            """
            SELECT aml.account_id, aml.partner_id,
                   SUM(CASE WHEN aml.date < %(fy_start)s THEN aml.balance ELSE 0 END) AS before_fy,
                   SUM(CASE WHEN aml.date >= %(fy_start)s AND aml.date < %(date_from)s
                            THEN aml.balance ELSE 0 END) AS fy_open,
                   SUM(CASE WHEN aml.date >= %(date_from)s THEN aml.debit ELSE 0 END) AS debit,
                   SUM(CASE WHEN aml.date >= %(date_from)s THEN aml.credit ELSE 0 END) AS credit
            FROM account_move_line aml
            WHERE aml.parent_state = 'posted'
              AND aml.company_id = %(company_id)s
              AND aml.date <= %(date_to)s
            GROUP BY aml.account_id, aml.partner_id
            """,
            fy_start=fy_start, date_from=date_from, date_to=date_to, company_id=company.id,
        ))
        raw = self.env.cr.dictfetchall()

        accounts = self.env['account.account'].with_company(company).browse(
            {r['account_id'] for r in raw})
        acc_info = {a.id: a for a in accounts}
        partners = {p.id: p for p in self.env['res.partner'].browse(
            {r['partner_id'] for r in raw if r['partner_id']})}

        per_account = {}
        undistributed = 0.0
        for r in raw:
            acc = acc_info[r['account_id']]
            if acc.include_initial_balance:
                opening = r['before_fy'] + r['fy_open']
            else:
                opening = r['fy_open']
                undistributed += r['before_fy']
            entry = per_account.setdefault(acc.id, {'opening': 0.0, 'debit': 0.0, 'credit': 0.0, 'parties': {}})
            entry['opening'] += opening
            entry['debit'] += r['debit']
            entry['credit'] += r['credit']
            if acc.account_type in PARTY_ACCOUNT_TYPES:
                party = entry['parties'].setdefault(r['partner_id'] or 0,
                                                    {'opening': 0.0, 'debit': 0.0, 'credit': 0.0})
                party['opening'] += opening
                party['debit'] += r['debit']
                party['credit'] += r['credit']

        def make_row(kind, code, name, vals):
            closing = vals['opening'] + vals['debit'] - vals['credit']
            open_dr, open_cr = _split(vals['opening'])
            close_dr, close_cr = _split(closing)
            return {
                'kind': kind, 'code': code, 'name': name,
                'open_dr': open_dr, 'open_cr': open_cr,
                'dr': vals['debit'], 'cr': vals['credit'],
                'close_dr': close_dr, 'close_cr': close_cr,
            }

        def is_zero(vals):
            closing = vals['opening'] + vals['debit'] - vals['credit']
            return all(abs(v) < ZERO for v in (vals['opening'], vals['debit'], vals['credit'], closing))

        rows = []
        for acc in sorted(accounts, key=lambda a: a.code or ''):
            vals = per_account[acc.id]
            if wizard.hide_zero and is_zero(vals):
                continue
            is_control = acc.account_type in PARTY_ACCOUNT_TYPES
            rows.append(make_row('control' if is_control else 'account', acc.code, acc.name, vals))
            if is_control:
                party_rows = []
                for pid, pvals in vals['parties'].items():
                    if wizard.hide_zero and is_zero(pvals):
                        continue
                    name = partners[pid].name if pid else '(No party)'
                    party_rows.append(make_row('party', '', name, pvals))
                rows.extend(sorted(party_rows, key=lambda r: (r['name'] or '').lower()))

        if abs(undistributed) >= ZERO:
            rows.append(make_row('undistributed', '', 'Undistributed Profits/Losses',
                                 {'opening': undistributed, 'debit': 0.0, 'credit': 0.0}))

        totals = {k: sum(r[k] for r in rows if r['kind'] != 'party')
                  for k in ('open_dr', 'open_cr', 'dr', 'cr', 'close_dr', 'close_cr')}
        return {
            'company': company,
            'date_from': date_from,
            'date_to': date_to,
            'rows': rows,
            'totals': totals,
        }
