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
        return lines.filtered(lambda l: l.amount_residual * sign > 0)

    @api.depends('state', 'amount_residual', 'partner_id', 'move_type')
    def _compute_advance_available(self):
        for move in self:
            amount = 0.0
            if move.state == 'posted' and move.payment_state not in ('paid', 'in_payment', 'reversed') and move.move_type in ('out_invoice', 'in_invoice'):
                amount = abs(sum(move._open_advance_lines().mapped('amount_residual')))
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
