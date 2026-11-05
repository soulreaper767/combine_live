from datetime import datetime

from odoo import _, fields, models

VOUCHER_TYPES = [
    ('all', 'All vouchers'),
    ('bank_receipt', 'Bank Receipts'),
    ('bank_payment', 'Bank Payments'),
    ('cash_receipt', 'Cash Receipts'),
    ('cash_payment', 'Cash Payments'),
    ('journal', 'Journal Vouchers'),
]
TITLE_TO_TYPE = {
    'Bank Receipt Voucher': 'bank_receipt', 'Bank Payment Voucher': 'bank_payment',
    'Cash Receipt Voucher': 'cash_receipt', 'Cash Payment Voucher': 'cash_payment',
    'Journal Voucher': 'journal',
}


def _moves_vouchers(env, wizard, date_from, date_to, posted_only, journals=None):
    """Bank / cash / journal vouchers (entries, not invoices) in the period, with their type."""
    dom = [('company_id', '=', env.company.id), ('move_type', '=', 'entry'),
           ('journal_id.type', 'in', ('bank', 'cash', 'general')),
           ('date', '>=', date_from), ('date', '<=', date_to)]
    dom.append(('state', '=', 'posted') if posted_only else ('state', '!=', 'cancel'))
    if journals:
        dom.append(('journal_id', 'in', journals.ids))
    helper = env['partner_ledger_qty.voucher.mixin']
    out = []
    for move in env['account.move'].search(dom, order='date, name, id'):
        vtype = TITLE_TO_TYPE.get(helper._voucher_title(move), 'journal')
        lines = move.line_ids.filtered(lambda l: l.debit or l.credit)
        parties = lines.partner_id.commercial_partner_id
        if (wizard.partner_ids or wizard.party_type_ids) and not any(wizard._register_partner_ok(p) for p in parties):
            continue
        payment = move.origin_payment_id if 'origin_payment_id' in move._fields else False
        narration = move.ref or (payment and payment.memo if payment and 'memo' in payment._fields else '') or \
            next((l.name for l in lines if l.name), '')
        out.append({'move': move, 'type': vtype, 'lines': lines, 'parties': parties,
                    'narration': narration or '', 'amount': sum(lines.mapped('debit'))})
    return out


class VoucherRegisterWizard(models.TransientModel):
    """Bank Receipts / Bank Payments / Cash Receipts / Cash Payments /
    Journal Vouchers register - voucher by voucher with its accounts, or a
    one-line-per-voucher day book per journal."""
    _name = 'combine.voucher.register.wizard'
    _inherit = 'combine.register.mixin'
    _description = 'Bank & Cash Voucher Register'
    _register_report_xmlid = 'partner_ledger_qty.action_report_voucher_register'

    voucher_type = fields.Selection(VOUCHER_TYPES, string='Vouchers', required=True, default='all')
    journal_ids = fields.Many2many('account.journal', 'combine_vreg_journal_rel', 'wizard_id', 'journal_id',
                                   string='Bank / Cash Books', domain="[('type', 'in', ('bank', 'cash', 'general'))]",
                                   help='Leave empty for all.')
    detail = fields.Selection([('summary', 'One line per voucher'), ('detail', 'Every account line')],
                              required=True, default='summary')
    posted_only = fields.Boolean(string='Posted only', default=True)

    def _register_data(self):
        self.ensure_one()
        vouchers = [v for v in _moves_vouchers(self.env, self, self.date_from, self.date_to, self.posted_only, self.journal_ids)
                    if self.voucher_type == 'all' or v['type'] == self.voucher_type]
        labels = dict(VOUCHER_TYPES)
        groups = []
        if self.detail == 'summary':
            columns = [(_('Date'), 'd'), (_('Voucher No.'), 't'), (_('Type'), 'c'), (_('Party'), 't'),
                       (_('Narration'), 't'), (_('Cheque / Ref.'), 'c'), (_('Receipts / Debit'), 'n'), (_('Payments / Credit'), 'n')]
            by_journal = {}
            for v in vouchers:
                by_journal.setdefault(v['move'].journal_id, []).append(v)
            for journal in sorted(by_journal, key=lambda j: j.name):
                rows = []
                for v in by_journal[journal]:
                    receipt = v['type'] in ('bank_receipt', 'cash_receipt') or v['type'] == 'journal'
                    payment = v['move'].origin_payment_id if 'origin_payment_id' in v['move']._fields else False
                    cheque = (payment.check_number if payment and 'check_number' in payment._fields else '') or ''
                    rows.append([v['move'].date, v['move'].name, labels[v['type']].rstrip('s'),
                                 ', '.join(v['parties'].mapped('name')), v['narration'], cheque,
                                 v['amount'] if receipt else 0.0, 0.0 if receipt else v['amount']])
                groups.append({'title': journal.name, 'sub': _('Vouchers: %s', len(rows)), 'rows': rows,
                               'totals': {6: sum(r[6] for r in rows), 7: sum(r[7] for r in rows)}})
            totals = {6: sum(g['totals'][6] for g in groups), 7: sum(g['totals'][7] for g in groups)} if groups else {}
        else:
            columns = [(_('Account Code'), 'c'), (_('Account'), 't'), (_('Party'), 't'), (_('Narration'), 't'),
                       (_('Debit'), 'n'), (_('Credit'), 'n')]
            for v in vouchers:
                move = v['move']
                rows = [[l.account_id.code or '', l.account_id.name or '', l.partner_id.commercial_partner_id.name or '',
                         l.name or '', l.debit, l.credit] for l in v['lines'].sorted(lambda l: (-l.debit, l.id))]
                sub = ' | '.join(p for p in (fields.Date.to_string(move.date), labels[v['type']].rstrip('s'),
                                             move.journal_id.name, v['narration'],
                                             dict(move._fields['state'].selection).get(move.state)) if p)
                groups.append({'title': move.name, 'sub': sub, 'rows': rows,
                               'totals': {4: sum(r[4] for r in rows), 5: sum(r[5] for r in rows)}})
            totals = {4: sum(g['totals'][4] for g in groups), 5: sum(g['totals'][5] for g in groups)} if groups else {}
        filters = self._register_filter_lines()
        if self.journal_ids:
            filters.append((_('Books'), ', '.join(self.journal_ids.mapped('name'))))
        if not self.posted_only:
            filters.append((_('Including'), _('draft vouchers')))
        title = labels[self.voucher_type] + ' ' + _('Register') if self.voucher_type != 'all' else _('Bank & Cash Voucher Register')
        return {'title': title, 'filters': filters, 'columns': columns, 'groups': groups, 'totals': totals}


class DailyDocumentsWizard(models.TransientModel):
    """Every document of the selected days in one report: sales, purchases,
    stores and accounts - each document type in its own block with count
    and totals."""
    _name = 'combine.daily.documents.wizard'
    _inherit = 'combine.register.mixin'
    _description = 'Daily Documents Register'
    _register_report_xmlid = 'partner_ledger_qty.action_report_daily_documents'

    date_from = fields.Date(default=fields.Date.context_today)
    scope = fields.Selection([('all', 'All documents'), ('sales', 'Sales'), ('purchase', 'Purchases'),
                              ('stores', 'Stores'), ('accounts', 'Accounts (vouchers)')],
                             string='Documents', required=True, default='all')
    posted_only = fields.Boolean(string='Completed / posted only', default=False,
                                 help='Leave off to see drafts too - the day\'s full work.')

    # ------------------------------------------------------------------ helpers
    def _in_range(self, field, is_datetime):
        if is_datetime:
            start = fields.Datetime.to_datetime(self.date_from)
            return [(field, '>=', start), (field, '<', fields.Datetime.add(fields.Datetime.to_datetime(self.date_to), days=1))]
        return [(field, '>=', self.date_from), (field, '<=', self.date_to)]

    @staticmethod
    def _state(rec):
        if 'state' not in rec._fields:
            return ''
        return dict(rec._fields['state']._description_selection(rec.env)).get(rec.state, rec.state or '')

    def _date_of(self, value):
        if not value:
            return False
        return fields.Date.context_today(self, value) if isinstance(value, datetime) else value

    def _sources(self):
        """(scope, label, model, date field, is datetime, extra domain, done states, partner, reference, qty, amount)"""
        E = self.env
        co = [('company_id', '=', E.company.id)]
        qty_lines = lambda field, qf: (lambda r: sum(r[field].mapped(qf)))
        src = [
            ('sales', _('Contracts / Sales Orders'), 'sale.order', 'date_order', True, co + [('state', '!=', 'cancel')], ('sale',),
             'partner_id', lambda r: r.client_order_ref, qty_lines('order_line', 'product_uom_qty'), lambda r: r.amount_total),
            ('sales', _('Sales Tax Invoices'), 'account.move', 'invoice_date', False, co + [('move_type', '=', 'out_invoice'), ('state', '!=', 'cancel')], ('posted',),
             'partner_id', lambda r: r.ref or r.invoice_origin, qty_lines('invoice_line_ids', 'quantity'), lambda r: r.amount_total),
            ('sales', _('Credit Notes'), 'account.move', 'invoice_date', False, co + [('move_type', '=', 'out_refund'), ('state', '!=', 'cancel')], ('posted',),
             'partner_id', lambda r: r.ref or r.invoice_origin, qty_lines('invoice_line_ids', 'quantity'), lambda r: r.amount_total),
            ('sales', _('Deliveries'), 'stock.picking', 'date_done', True, co + [('picking_type_code', '=', 'outgoing'), ('state', '=', 'done')], ('done',),
             'partner_id', lambda r: r.origin, qty_lines('move_ids', 'quantity'), None),
            ('purchase', _('Purchase Orders'), 'purchase.order', 'date_order', True, co + [('state', '!=', 'cancel')], ('purchase', 'done'),
             'partner_id', lambda r: r.partner_ref, qty_lines('order_line', 'product_qty'), lambda r: r.amount_total),
            ('purchase', _('Vendor Bills'), 'account.move', 'invoice_date', False, co + [('move_type', '=', 'in_invoice'), ('state', '!=', 'cancel')], ('posted',),
             'partner_id', lambda r: r.ref, qty_lines('invoice_line_ids', 'quantity'), lambda r: r.amount_total),
            ('purchase', _('Debit Notes'), 'account.move', 'invoice_date', False, co + [('move_type', '=', 'in_refund'), ('state', '!=', 'cancel')], ('posted',),
             'partner_id', lambda r: r.ref, qty_lines('invoice_line_ids', 'quantity'), lambda r: r.amount_total),
            ('purchase', _('Goods Receipts (stock)'), 'stock.picking', 'date_done', True, co + [('picking_type_code', '=', 'incoming'), ('state', '=', 'done')], ('done',),
             'partner_id', lambda r: r.origin, qty_lines('move_ids', 'quantity'), None),
        ]
        stores = [
            (_('Demand Notes'), 'combine.demand.note', 'date', False, ('submitted',), None, lambda r: r.department, 'line_ids', 'qty'),
            (_('Gate Passes Inward (IGP)'), 'combine.gate.pass.in', 'date', True, ('in', 'inspected', 'done'), 'partner_id', lambda r: r.party_ref, 'line_ids', 'qty_received'),
            (_('Quality Inspections'), 'combine.inspection', 'date', False, ('done',), 'partner_id', lambda r: r.gate_pass_id.name, 'line_ids', 'qty_accepted'),
            (_('Goods Receipt Notes (GRN)'), 'combine.grn', 'date', False, ('done',), 'partner_id', lambda r: r.gate_pass_id.name, 'line_ids', 'qty'),
            (_('Gate Passes Outward (OGP)'), 'combine.gate.pass.out', 'date', True, ('out',), 'partner_id', lambda r: r.invoice_ref, 'line_ids', 'qty'),
            (_('Material Issues to Production'), 'combine.material.issue', 'date', False, ('done',), None, lambda r: r.department_id.name, 'line_ids', 'qty'),
            (_('Conversion Orders'), 'combine.conversion.order', 'date', False, None, 'partner_id', lambda r: '', None, None),
        ]
        for label, model, dfield, is_dt, done, pfield, ref, lfield, qf in stores:
            if model in E:
                src.append(('stores', label, model, dfield, is_dt, [('state', '!=', 'cancel')], done, pfield, ref,
                            qty_lines(lfield, qf) if lfield else None,
                            (lambda r: r.total_value) if model == 'combine.material.issue' else None))
        return src

    # ------------------------------------------------------------------ data
    def _register_data(self):
        self.ensure_one()
        columns = [(_('Date'), 'd'), (_('Document'), 't'), (_('Party / Department'), 't'), (_('Reference'), 't'),
                   (_('Status'), 'c'), (_('Quantity'), 'q'), (_('Amount'), 'n')]
        groups = []
        for scope, label, model, dfield, is_dt, dom, done, pfield, ref, qty, amount in self._sources():
            if self.scope not in ('all', scope):
                continue
            Model = self.env[model]
            dom = list(dom) + self._in_range(dfield, is_dt)
            if self.posted_only and done:
                dom.append(('state', 'in', done))
            rows = []
            for rec in Model.search(dom, order='%s, id' % dfield):
                partner = rec[pfield] if pfield else False
                if (self.partner_ids or self.party_type_ids) and not (partner and self._register_partner_ok(partner)):
                    continue
                who = partner.commercial_partner_id.name if partner else (ref(rec) if model in ('combine.demand.note', 'combine.material.issue') else '')
                rows.append([self._date_of(rec[dfield]), rec.display_name, who or '',
                             '' if model in ('combine.demand.note', 'combine.material.issue') else (ref(rec) or ''),
                             self._state(rec), qty(rec) if qty else None, amount(rec) if amount else None])
            if rows:
                totals = {6: sum(r[6] for r in rows if r[6])} if amount else {}
                groups.append({'title': label, 'sub': _('Documents: %s', len(rows)), 'rows': rows, 'totals': totals})
        if self.scope in ('all', 'accounts'):
            labels = dict(VOUCHER_TYPES)
            by_type = {}
            for v in _moves_vouchers(self.env, self, self.date_from, self.date_to, self.posted_only):
                by_type.setdefault(v['type'], []).append(v)
            for vtype, _label in VOUCHER_TYPES[1:]:
                vs = by_type.get(vtype)
                if not vs:
                    continue
                rows = [[v['move'].date, v['move'].name, ', '.join(v['parties'].mapped('name')), v['narration'],
                         self._state(v['move']), None, v['amount']] for v in vs]
                groups.append({'title': labels[vtype], 'sub': _('Vouchers: %s', len(rows)), 'rows': rows,
                               'totals': {6: sum(r[6] for r in rows)}})
        filters = self._register_filter_lines()
        filters.append((_('Documents'), dict(self._fields['scope'].selection)[self.scope]))
        filters.append((_('Status'), _('completed / posted only') if self.posted_only else _('all, including drafts')))
        filters.append((_('Count'), _('Documents: %s', sum(len(g['rows']) for g in groups))))
        return {'title': _('Daily Documents Register'), 'filters': filters, 'columns': columns,
                'groups': groups, 'totals': {}}
