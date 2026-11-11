"""Four party control accounts: Customers, Vendors, Customer Advances,
Vendor Advances.

- Every customer / vendor points to the two control accounts (new ones by
  default). Posted entries are never edited: old invoices and bills keep
  their old account and are settled on it as before.
- Every other receivable / payable account is archived as soon as nothing
  is open on it any more (at setup, then daily) - so it can never block a
  payment of an old document.
- Advances: "Advance" on a payment sends it to the advance account;
  "Apply Advance" on an invoice / bill settles it from the party's open
  advances with a transfer entry, reconciled on both sides.
"""
import logging

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

CONTROL_ACCOUNTS = {
    # key: (code, name, account_type)
    'customer': ('3.09.15', 'TRADE DEBTORS - CONTROL', 'asset_receivable'),
    'vendor': ('2.07.15', 'TRADE CREDITORS - CONTROL', 'liability_payable'),
    'customer_advance': ('2.07.16', 'ADVANCES FROM CUSTOMERS', 'liability_payable'),
    'vendor_advance': ('3.09.16', 'ADVANCES TO SUPPLIERS', 'asset_receivable'),
}


class ResCompany(models.Model):
    _inherit = 'res.company'

    x_customer_control_id = fields.Many2one('account.account', string='Customers Control Account')
    x_vendor_control_id = fields.Many2one('account.account', string='Vendors Control Account')
    x_customer_advance_id = fields.Many2one('account.account', string='Customer Advances Account')
    x_vendor_advance_id = fields.Many2one('account.account', string='Vendor Advances Account')

    def _party_accounts(self):
        self.ensure_one()
        return self.x_customer_control_id | self.x_vendor_control_id | self.x_customer_advance_id | self.x_vendor_advance_id

    # ------------------------------------------------------------------ setup
    def _setup_party_control_accounts(self):
        """Idempotent: creates the 4 accounts if missing, makes them the
        defaults, points every party to the controls, archives the other
        party accounts that have nothing open. Edits no journal entry."""
        self.ensure_one()
        company = self
        env = self.env(context=dict(self.env.context, active_test=False, allowed_company_ids=[company.id]))
        Account = env['account.account'].with_company(company)
        log = []
        accounts = {}
        for key, (code, name, atype) in CONTROL_ACCOUNTS.items():
            acc = Account.search([('code', '=', code)], limit=1)
            if not acc:
                acc = Account.create({'code': code, 'name': name, 'account_type': atype, 'reconcile': True})
                log.append('created %s %s' % (code, name))
            elif not acc.active:
                acc.active = True
            accounts[key] = acc
        company.write({'x_customer_control_id': accounts['customer'].id, 'x_vendor_control_id': accounts['vendor'].id,
                       'x_customer_advance_id': accounts['customer_advance'].id, 'x_vendor_advance_id': accounts['vendor_advance'].id})
        IrDefault = env['ir.default']
        IrDefault.set('res.partner', 'property_account_receivable_id', accounts['customer'].id, company_id=company.id)
        IrDefault.set('res.partner', 'property_account_payable_id', accounts['vendor'].id, company_id=company.id)
        Partner = env['res.partner'].with_company(company)
        rec = Partner.search([('property_account_receivable_id', '!=', accounts['customer'].id)])
        if rec:
            rec.write({'property_account_receivable_id': accounts['customer'].id})
        pay = Partner.search([('property_account_payable_id', '!=', accounts['vendor'].id)])
        if pay:
            pay.write({'property_account_payable_id': accounts['vendor'].id})
        log.append('parties pointed to the controls: %s receivable, %s payable' % (len(rec), len(pay)))
        archived = company._archive_settled_party_accounts()
        log.append('archived (nothing open): %s' % (', '.join(archived) or '-'))
        _logger.info('Party control accounts (%s): %s', company.name, log)
        return log

    def _archive_settled_party_accounts(self):
        """Archive receivable / payable accounts other than the 4 when nothing
        is open on them and nothing still uses them. Posted lines stay."""
        self.ensure_one()
        keep = self._party_accounts()
        if len(keep) < 4:
            return []
        Account = self.env['account.account'].with_company(self)
        AML = self.env['account.move.line'].sudo()
        candidates = Account.search([('account_type', 'in', ('asset_receivable', 'liability_payable')),
                                     ('id', 'not in', keep.ids), ('company_ids', 'in', self.id)])
        archived = []
        for acc in candidates:
            if AML.search_count([('account_id', '=', acc.id), ('parent_state', '=', 'draft')], limit=1):
                continue
            if AML.search_count([('account_id', '=', acc.id), ('parent_state', '=', 'posted'), ('reconciled', '=', False),
                                 ('amount_residual', '!=', 0)], limit=1):
                continue
            if self.env['res.partner'].with_context(active_test=False).with_company(self).search_count(
                    ['|', ('property_account_receivable_id', '=', acc.id), ('property_account_payable_id', '=', acc.id)], limit=1):
                continue
            if self.env['account.journal'].search_count(['|', ('default_account_id', '=', acc.id), ('suspense_account_id', '=', acc.id)], limit=1):
                continue
            try:
                with self.env.cr.savepoint():
                    acc.active = False
                archived.append(acc.code)
            except Exception as e:  # used somewhere Odoo protects - leave it active
                _logger.info('Party account %s kept active: %s', acc.code, e)
        return archived

    @api.model
    def _cron_archive_settled_party_accounts(self):
        for company in self.search([]):
            if company.x_customer_control_id:
                company.with_company(company)._archive_settled_party_accounts()

    # ------------------------------------------------------------------ remap
    REMAP_TABLE = 'combine_party_account_remap'

    def _remap_party_lines_to_controls(self):
        """Replace the old receivable / payable account by the control account
        on every journal line (posted, draft, cancelled) and payment of this
        company. Only the account changes - amounts, dates, numbers, parties,
        reconciliations and open amounts stay exactly as they are (old and new
        accounts are both reconcilable party accounts). Every change is first
        recorded in combine_party_account_remap so it can be reversed exactly
        (_restore_party_account_remap)."""
        self.ensure_one()
        cust, vend = self.x_customer_control_id, self.x_vendor_control_id
        if not cust or not vend:
            return ['controls missing - nothing remapped']
        cr = self.env.cr
        Account = self.env['account.account'].with_context(active_test=False)
        old = Account.search([('account_type', 'in', ('asset_receivable', 'liability_payable')),
                              ('id', 'not in', self._party_accounts().ids), ('company_ids', 'in', self.id)])
        cr.execute(f"""CREATE TABLE IF NOT EXISTS {self.REMAP_TABLE} (
                           id serial PRIMARY KEY, company_id int, res_model varchar, res_id int,
                           old_account_id int, new_account_id int, remapped_at timestamp DEFAULT (now() AT TIME ZONE 'UTC'))""")
        self.env.flush_all()
        log = []
        for old_ids, new in ((old.filtered(lambda a: a.account_type == 'asset_receivable').ids, cust.id),
                             (old.filtered(lambda a: a.account_type == 'liability_payable').ids, vend.id)):
            if not old_ids:
                continue
            for table, model, column in (('account_move_line', 'account.move.line', 'account_id'),
                                         ('account_payment', 'account.payment', 'destination_account_id')):
                cr.execute(f"""INSERT INTO {self.REMAP_TABLE} (company_id, res_model, res_id, old_account_id, new_account_id)
                               SELECT %s, %s, id, {column}, %s FROM {table} WHERE {column} = ANY(%s) AND company_id = %s""",
                           (self.id, model, new, old_ids, self.id))
                cr.execute(f"SELECT count(*) FROM {table} WHERE {column} = ANY(%s) AND company_id = %s", (old_ids, self.id))
                count = cr.fetchone()[0]
                cr.execute(f"UPDATE {table} SET {column} = %s WHERE {column} = ANY(%s) AND company_id = %s",
                           (new, old_ids, self.id))
                if count:
                    log.append('%s -> %s: %s %s' % (Account.browse(new).code, model, count, 'records'))
        self.env.invalidate_all()
        log.append('archived: %s' % (', '.join(self._archive_settled_party_accounts()) or '-'))
        _logger.info('Party lines remapped to the control accounts (%s): %s', self.name, log)
        return log

    # old non-party advance accounts whose lines are party balances -> the party advance account
    ADVANCE_ACCOUNT_CODES = {'3.10.04.0001': 'x_vendor_advance_id'}

    def _remap_advance_lines(self):
        """Lines on the old (non-party) advance accounts carry a party but never
        reached the partner ledger; put them on the party advance account
        (recorded first, reversible), then archive the old account."""
        self.ensure_one()
        cr = self.env.cr
        Account = self.env['account.account'].with_context(active_test=False)
        self.env.flush_all()
        log = []
        for code, field in self.ADVANCE_ACCOUNT_CODES.items():
            old = Account.search([('code', '=', code), ('company_ids', 'in', self.id),
                                  ('account_type', 'not in', ('asset_receivable', 'liability_payable'))], limit=1)
            new = self[field]
            if not old or not new:
                continue
            cr.execute(f"""INSERT INTO {self.REMAP_TABLE} (company_id, res_model, res_id, old_account_id, new_account_id)
                           SELECT %s, 'account.move.line', id, account_id, %s FROM account_move_line
                           WHERE account_id = %s AND company_id = %s""", (self.id, new.id, old.id, self.id))
            cr.execute("SELECT count(*) FROM account_move_line WHERE account_id = %s AND company_id = %s", (old.id, self.id))
            count = cr.fetchone()[0]
            cr.execute("UPDATE account_move_line SET account_id = %s WHERE account_id = %s AND company_id = %s RETURNING id",
                       (new.id, old.id, self.id))
            moved = self.env['account.move.line'].browse([r[0] for r in cr.fetchall()])
            self.env.invalidate_all()
            # the old account was not reconcilable, so Odoo kept no open amount on these lines;
            # on the (reconcilable) advance account they are open advances - let Odoo compute that
            AML = self.env['account.move.line']
            for fname in ('amount_residual', 'amount_residual_currency', 'reconciled'):
                self.env.add_to_compute(AML._fields[fname], moved)
            self.env.flush_all()
            log.append('%s -> %s: %s lines' % (code, new.code, count))
            if not self.env['account.journal'].search_count(['|', ('default_account_id', '=', old.id), ('suspense_account_id', '=', old.id)], limit=1):
                try:
                    with cr.savepoint():
                        old.active = False
                    log.append('archived %s' % code)
                except Exception as e:
                    _logger.info('%s kept active: %s', code, e)
        _logger.info('Advance lines moved to the party advance accounts (%s): %s', self.name, log)
        return log

    # heads users created (not party accounts) that the merge took:
    # CANTEEN / HAIDRI - SHOP / WASHER MAN contractors, EXPENSES PAYABLE - SITE
    RESTORE_HEAD_CODES = ('2.07.06', '2.07.10', '2.07.11', '2.11.02.0001')

    def _restore_user_heads(self):
        """Bring back the heads users created themselves that the party merge
        (19.0.7.11.0) took as party accounts - e.g. EXPENSES PAYABLE - SITE,
        contractor accounts: reactivate them and put every line the merge
        moved off them back on them, exactly from the recorded table. Heads
        from the imported chart (created by the system) stay merged, the
        supplier-advance move stays. A matching between a restored line and
        a line that stayed on the control account would join two different
        accounts, so it is undone (and logged) for re-matching."""
        self.ensure_one()
        cr = self.env.cr
        table = self.REMAP_TABLE
        cr.execute("SELECT to_regclass(%s)", (table,))
        if not cr.fetchone()[0]:
            return ['no merge record - nothing to restore']
        cr.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS restored_at timestamp")
        Account = self.env['account.account'].with_context(active_test=False)
        cr.execute(f"SELECT DISTINCT old_account_id FROM {table} WHERE company_id = %s AND restored_at IS NULL", (self.id,))
        olds = Account.browse([r[0] for r in cr.fetchall()]).exists()
        heads = olds.filtered(lambda a: a.code in self.RESTORE_HEAD_CODES)
        if not heads:
            return ['none of the user-created heads is in the merge record']
        log = ['heads: %s' % ', '.join('%s %s' % (a.code, a.name) for a in heads)]
        heads.write({'active': True})
        self.env.flush_all()
        restored = []
        for tbl, model, column in (('account_move_line', 'account.move.line', 'account_id'),
                                   ('account_payment', 'account.payment', 'destination_account_id')):
            cr.execute(f"""UPDATE {tbl} t SET {column} = r.old_account_id FROM {table} r
                           WHERE r.res_model = %s AND r.res_id = t.id AND r.company_id = %s AND r.restored_at IS NULL
                             AND r.old_account_id = ANY(%s) AND t.{column} = r.new_account_id
                           RETURNING t.id""", (model, self.id, heads.ids))
            ids = [r[0] for r in cr.fetchall()]
            cr.execute(f"""UPDATE {table} SET restored_at = (now() AT TIME ZONE 'UTC')
                           WHERE res_model = %s AND company_id = %s AND old_account_id = ANY(%s) AND restored_at IS NULL""",
                       (model, self.id, heads.ids))
            log.append('%s back on their heads: %s' % (model, len(ids)))
            if model == 'account.move.line':
                restored = ids
        self.env.invalidate_all()
        lines = self.env['account.move.line'].browse(restored)
        partials = lines.matched_debit_ids | lines.matched_credit_ids
        cross = partials.filtered(lambda p: p.debit_move_id.account_id != p.credit_move_id.account_id)
        if cross:
            log.append('matchings undone (re-match them): %s' % ', '.join(
                '%s / %s' % (p.debit_move_id.move_id.name, p.credit_move_id.move_id.name) for p in cross))
            cross.unlink()
        AML = self.env['account.move.line']
        for fname in ('amount_residual', 'amount_residual_currency', 'reconciled'):
            self.env.add_to_compute(AML._fields[fname], lines)
        self.env.flush_all()
        _logger.info('User-created heads restored (%s): %s', self.name, log)
        return log

    def _restore_party_account_remap(self):
        """Undo _remap_party_lines_to_controls exactly, from the recorded table
        (reactivates the old accounts first). Not called automatically."""
        self.ensure_one()
        cr = self.env.cr
        cr.execute(f"SELECT DISTINCT old_account_id FROM {self.REMAP_TABLE} WHERE company_id = %s", (self.id,))
        self.env['account.account'].with_context(active_test=False).browse([r[0] for r in cr.fetchall()]).write({'active': True})
        self.env.flush_all()
        for table, model, column in (('account_move_line', 'account.move.line', 'account_id'),
                                     ('account_payment', 'account.payment', 'destination_account_id')):
            cr.execute(f"""UPDATE {table} t SET {column} = r.old_account_id FROM {self.REMAP_TABLE} r
                           WHERE r.res_model = %s AND r.res_id = t.id AND r.company_id = %s""", (model, self.id))
        self.env.invalidate_all()
        return True


# ============================================================ advances
class AccountPayment(models.Model):
    _inherit = 'account.payment'

    x_is_advance = fields.Boolean(string='Advance', help='Money received from a customer / paid to a vendor before the invoice / bill: '
                                                         'it goes to the advance account and is applied later with "Apply Advance".')

    @api.depends('journal_id', 'partner_id', 'partner_type', 'x_is_advance')
    def _compute_destination_account_id(self):
        super()._compute_destination_account_id()
        for pay in self.filtered('x_is_advance'):
            company = pay.company_id
            acc = company.x_customer_advance_id if pay.partner_type == 'customer' else company.x_vendor_advance_id
            if acc:
                pay.destination_account_id = acc


class AccountMove(models.Model):
    _inherit = 'account.move'

    x_advance_available = fields.Monetary(string='Advance Available', compute='_compute_advance_available',
                                          currency_field='company_currency_id')

    def _advance_account(self):
        self.ensure_one()
        if self.move_type in ('out_invoice', 'out_receipt'):
            return self.company_id.x_customer_advance_id, -1   # advances sit as credit
        if self.move_type in ('in_invoice', 'in_receipt'):
            return self.company_id.x_vendor_advance_id, 1      # advances sit as debit
        return self.env['account.account'], 0

    def _open_advance_lines(self):
        self.ensure_one()
        account, sign = self._advance_account()
        if not account or not self.commercial_partner_id:
            return self.env['account.move.line']
        lines = self.env['account.move.line'].search([
            ('account_id', '=', account.id), ('partner_id', 'child_of', self.commercial_partner_id.id),
            ('parent_state', '=', 'posted'), ('reconciled', '=', False), ('company_id', '=', self.company_id.id)])
        # all open lines, both directions (an advance paid and a part returned / adjusted net off)
        lines = lines.filtered(lambda l: not l.company_currency_id.is_zero(l.amount_residual))
        return lines if sign * sum(lines.mapped('amount_residual')) > 0 else lines.browse()

    @api.depends('state', 'amount_residual', 'partner_id', 'move_type')
    def _compute_advance_available(self):
        for move in self:
            amount = 0.0
            if move.state == 'posted' and move.payment_state not in ('paid', 'in_payment', 'reversed') and move.move_type in ('out_invoice', 'in_invoice'):
                amount = abs(sum(move._open_advance_lines().mapped('amount_residual')))  # net of debits and credits
            move.x_advance_available = amount

    def action_apply_advance(self):
        """Settle this invoice / bill from the party's open advances: transfer
        entry advance account <-> this document's receivable / payable account,
        both legs reconciled."""
        for move in self:
            if move.state != 'posted' or move.move_type not in ('out_invoice', 'in_invoice'):
                raise UserError(_('Apply Advance works on a posted customer invoice or vendor bill.'))
            advances = move._open_advance_lines()
            if not advances:
                raise UserError(_('%s has no open advance to apply. Record the advance as a payment with "Advance" ticked first.',
                                  move.commercial_partner_id.name))
            term_lines = move.line_ids.filtered(lambda l: l.account_id.account_type in ('asset_receivable', 'liability_payable')
                                                and not l.reconciled)
            if not term_lines:
                raise UserError(_('%s is already settled.', move.name))
            due = abs(sum(term_lines.mapped('amount_residual')))
            available = abs(sum(advances.mapped('amount_residual')))
            amount = min(due, available)
            account, _sign = move._advance_account()
            target = term_lines[0].account_id
            customer = move.move_type == 'out_invoice'
            journal = self.env['account.journal'].search([('type', '=', 'general'), ('company_id', '=', move.company_id.id)], limit=1)
            if not journal:
                raise UserError(_('Create a Miscellaneous journal first (Accounting > Configuration > Journals).'))
            partner = move.commercial_partner_id
            label = _('Advance applied to %s', move.name)
            # customer: Dr advance (clears its credit) / Cr receivable;  vendor: Dr payable / Cr advance
            adv_line = {'account_id': account.id, 'partner_id': partner.id, 'name': label,
                        'debit': amount if customer else 0.0, 'credit': 0.0 if customer else amount}
            doc_line = {'account_id': target.id, 'partner_id': partner.id, 'name': label,
                        'debit': 0.0 if customer else amount, 'credit': amount if customer else 0.0}
            entry = self.env['account.move'].create({
                'move_type': 'entry', 'journal_id': journal.id, 'date': fields.Date.context_today(self),
                'ref': label, 'line_ids': [Command.create(adv_line), Command.create(doc_line)]})
            entry.action_post()
            (entry.line_ids.filtered(lambda l: l.account_id == target) | term_lines.filtered(lambda l: l.account_id == target)).reconcile()
            (entry.line_ids.filtered(lambda l: l.account_id == account) | advances).reconcile()
            move.message_post(body=_('Advance of %(amt)s applied (%(entry)s).', amt=move.currency_id.format(amount), entry=entry.name))
        return True
