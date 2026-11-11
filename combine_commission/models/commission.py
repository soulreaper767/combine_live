"""Commission agents as parties: booking, commission bills, state.

Strict rule for this module: nothing it does on install, and nothing it
does automatically, changes a record that existed before. Commission lines
created by combine001 before this module was installed stay exactly as
they are ("Not booked") until a Finance Manager deliberately books them
with "Book Commission".
"""
from collections import defaultdict

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

EXPENSE_CODE = '6.02.05.0001'   # COMMISSION ON YARN SALES
ACCRUAL_CODE = '2.13.02.0003'   # UNBILLED INVOICES (COMMISSION)

COMMISSION_STATES = [
    ('not_booked', 'Not booked'),
    ('unbilled', 'Booked - not billed'),
    ('billed', 'Billed'),
    ('paid', 'Paid'),
]


class ResCompany(models.Model):
    _inherit = 'res.company'

    # Optional overrides - empty by default; the accounts are then found by code.
    x_commission_expense_account_id = fields.Many2one(
        'account.account', string='Commission Expense Account',
        help='Empty: %s (Commission on Yarn Sales).' % EXPENSE_CODE)
    x_commission_accrual_account_id = fields.Many2one(
        'account.account', string='Unbilled Commission Account',
        help='Empty: %s (Unbilled Invoices (Commission)).' % ACCRUAL_CODE)
    x_commission_journal_id = fields.Many2one(
        'account.journal', string='Commission Booking Journal',
        help='Empty: the Miscellaneous Operations journal.')

    def _combine_commission_setup(self, raise_if_missing=False):
        """(expense account, unbilled-commission account, booking journal)."""
        self.ensure_one()
        Acc = self.env['account.account'].sudo().with_company(self)
        Jrn = self.env['account.journal'].sudo()

        def by_code(code):
            return Acc.search([('code', '=', code), ('company_ids', 'in', self.id)], limit=1)

        expense = self.x_commission_expense_account_id or by_code(EXPENSE_CODE)
        accrual = self.x_commission_accrual_account_id or by_code(ACCRUAL_CODE)
        journal = self.x_commission_journal_id or Jrn.search(
            [('type', '=', 'general'), ('company_id', '=', self.id), ('code', '=', 'Misce')], limit=1) or Jrn.search(
            [('type', '=', 'general'), ('company_id', '=', self.id)], limit=1)
        if raise_if_missing and not (expense and accrual and journal):
            raise UserError(_(
                "Commission cannot be booked: the commission expense account (%(exp)s), the unbilled "
                "commission account (%(acc)s) or a miscellaneous journal is missing. Set them under "
                "Settings > Companies > %(co)s > Commission.", exp=EXPENSE_CODE, acc=ACCRUAL_CODE, co=self.name))
        return expense, accrual, journal

    def _combine_purchase_journal(self):
        self.ensure_one()
        journal = self.env['account.journal'].sudo().search(
            [('type', '=', 'purchase'), ('company_id', '=', self.id)], limit=1)
        if not journal:
            raise UserError(_('No purchase journal found for %s.', self.name))
        return journal


class CommissionAgent(models.Model):
    _inherit = 'combine001.commission.agent'

    x_line_count = fields.Integer(compute='_compute_x_totals', string='Commission Lines')
    x_amount_not_booked = fields.Monetary(compute='_compute_x_totals', string='Not booked')
    x_amount_unbilled = fields.Monetary(compute='_compute_x_totals', string='Booked - not billed')
    x_amount_billed = fields.Monetary(compute='_compute_x_totals', string='Billed - not paid')
    x_amount_paid = fields.Monetary(compute='_compute_x_totals', string='Paid')
    currency_id = fields.Many2one('res.currency', compute='_compute_x_currency')

    def _compute_x_currency(self):
        for agent in self:
            agent.currency_id = (agent.company_id or self.env.company).currency_id

    def _compute_x_totals(self):
        CL = self.env['combine001.commission.line']
        for agent in self:
            lines = CL.search([('agent_id', '=', agent.id)])
            totals = defaultdict(float)
            for line in lines:
                totals[line._x_state()] += line.commission_amount
            agent.x_line_count = len(lines)
            agent.x_amount_not_booked = totals['not_booked']
            agent.x_amount_unbilled = totals['unbilled']
            agent.x_amount_billed = totals['billed']
            agent.x_amount_paid = totals['paid']

    def action_combine_create_party(self):
        """Create the agent's party (vendor, Party Type "Commission Agent")
        and link it - done only when a user clicks it (here, or Bill
        Commission for an agent without a party)."""
        party_type = self.env.ref('combine_commission.party_type_commission_agent', raise_if_not_found=False)
        for agent in self.sudo():
            if agent.partner_id:
                continue
            agent.partner_id = self.env['res.partner'].sudo().create({
                'name': agent.name,
                'is_company': True,
                'supplier_rank': 1,
                'x_party_type_id': party_type.id if party_type else False,
            })
        return True

    def action_view_commission_lines(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('combine001.action_commission_line')
        action['domain'] = [('agent_id', '=', self.id)]
        action['context'] = {}
        return action


class CommissionLine(models.Model):
    _inherit = 'combine001.commission.line'

    x_accrual_move_id = fields.Many2one('account.move', string='Booking Entry', readonly=True, copy=False,
                                        index='btree_not_null')
    x_bill_line_id = fields.Many2one('account.move.line', string='Commission Bill Line', readonly=True,
                                     copy=False, ondelete='set null', index='btree_not_null')
    x_bill_id = fields.Many2one('account.move', related='x_bill_line_id.move_id', string='Commission Bill')
    x_commission_state = fields.Selection(COMMISSION_STATES, string='Commission Status',
                                          compute='_compute_x_commission_state',
                                          search='_search_x_commission_state')

    # ---------------------------------------------------------------- state
    def _x_active_bill(self):
        self.ensure_one()
        bill = self.x_bill_line_id.move_id
        return bill if bill and bill.state != 'cancel' else self.env['account.move']

    def _x_state(self):
        self.ensure_one()
        bill = self._x_active_bill()
        if bill:
            return 'paid' if bill.state == 'posted' and bill.payment_state in ('paid', 'in_payment') else 'billed'
        if self.payment_state == 'paid':
            return 'paid'
        if self.x_accrual_move_id and self.x_accrual_move_id.state == 'posted':
            return 'unbilled'
        return 'not_booked'

    @api.depends('x_accrual_move_id.state', 'x_bill_line_id.move_id.state',
                 'x_bill_line_id.move_id.payment_state', 'payment_state')
    def _compute_x_commission_state(self):
        for line in self:
            line.x_commission_state = line._x_state()

    def _search_x_commission_state(self, operator, value):
        values = {value} if isinstance(value, str) else set(value or [])
        matching = self.with_context(active_test=False).search([]).filtered(lambda l: l._x_state() in values).ids
        if operator in ('=', 'in'):
            return [('id', 'in', matching)]
        if operator in ('!=', 'not in'):
            return [('id', 'not in', matching)]
        raise UserError(_('Unsupported search on Commission Status.'))

    # -------------------------------------------------------------- booking
    def _combine_book(self, date=False):
        """Book these (not yet booked) commission lines.

        One entry per invoice and agent (date = invoice date), or - when a
        date is given - one entry per agent on that date. Returns the agents
        that could not be booked because they have no party."""
        to_book = self.filtered(lambda l: l._x_state() == 'not_booked' and l.payment_state != 'paid'
                                and not l.currency_id.is_zero(l.commission_amount))
        skipped = self.env['combine001.commission.agent']
        if not to_book:
            return skipped
        groups = defaultdict(lambda: self.env['combine001.commission.line'])
        for line in to_book:
            groups[(line.company_id or self.env.company, line.agent_id, False if date else line.invoice_id)] |= line
        Move = self.env['account.move'].sudo()
        for (company, agent, invoice), lines in groups.items():
            partner = agent.partner_id
            if not partner:
                skipped |= agent
                continue
            expense, accrual, journal = company._combine_commission_setup(raise_if_missing=True)
            line_vals, total = [], 0.0
            for cl in lines:
                amount = cl.currency_id.round(cl.commission_amount)
                total += amount
                line_vals.append(Command.create({
                    'account_id': accrual.id, 'partner_id': partner.id,
                    'name': _('Commission %(rate)s%% - %(inv)s - %(cust)s - %(item)s', rate='{:g}'.format(cl.rate),
                              inv=cl.invoice_id.name, cust=cl.partner_id.name or '',
                              item=cl.product_id.display_name or ''),
                    'debit': -amount if amount < 0 else 0.0, 'credit': amount if amount > 0 else 0.0,
                }))
            total = company.currency_id.round(total)
            if not company.currency_id.is_zero(total):
                line_vals.append(Command.create({
                    'account_id': expense.id, 'partner_id': partner.id,
                    'name': _('Commission - %s', agent.name),
                    'debit': total if total > 0 else 0.0, 'credit': -total if total < 0 else 0.0,
                }))
            move = Move.with_company(company).create({
                'move_type': 'entry',
                'journal_id': journal.id,
                'date': date or invoice.date,
                'ref': _('Commission - %(agent)s - %(src)s', agent=agent.name,
                         src=invoice.name if invoice else _('booked %s', fields.Date.to_string(date))),
                'x_commission_kind': 'booking',
                'line_ids': line_vals,
            })
            move.action_post()
            lines.sudo().write({'x_accrual_move_id': move.id})
        return skipped

    def _combine_unbook(self):
        """Reverse what these lines booked (used when they are removed)."""
        booked = self.filtered(lambda l: l.x_accrual_move_id.state == 'posted')
        groups = defaultdict(lambda: self.env['combine001.commission.line'])
        for line in booked:
            groups[line.x_accrual_move_id] |= line
        Move = self.env['account.move'].sudo()
        for origin, lines in groups.items():
            company = origin.company_id
            expense, accrual, journal = company._combine_commission_setup(raise_if_missing=True)
            partner = origin.line_ids.partner_id[:1]
            line_vals, total = [], 0.0
            for cl in lines:
                amount = cl.currency_id.round(cl.commission_amount)
                total += amount
                line_vals.append(Command.create({
                    'account_id': accrual.id, 'partner_id': partner.id,
                    'name': _('Reversal: commission %(rate)s%% - %(inv)s - %(item)s', rate='{:g}'.format(cl.rate),
                              inv=cl.invoice_id.name, item=cl.product_id.display_name or ''),
                    'debit': amount if amount > 0 else 0.0, 'credit': -amount if amount < 0 else 0.0,
                }))
            total = company.currency_id.round(total)
            if not company.currency_id.is_zero(total):
                line_vals.append(Command.create({
                    'account_id': expense.id, 'partner_id': partner.id,
                    'name': _('Reversal of commission - %s', origin.name),
                    'debit': -total if total < 0 else 0.0, 'credit': total if total > 0 else 0.0,
                }))
            vals = {'move_type': 'entry', 'journal_id': journal.id, 'ref': _('Reversal of %s', origin.name),
                    'x_commission_kind': 'reversal', 'line_ids': line_vals}
            try:
                with self.env.cr.savepoint():
                    move = Move.with_company(company).create(dict(vals, date=origin.date))
                    move.action_post()
            except UserError:
                # the booking's period is locked - reverse today instead
                move = Move.with_company(company).create(dict(vals, date=fields.Date.context_today(self)))
                move.action_post()

    def unlink(self):
        billed = self.filtered(lambda l: l._x_active_bill())
        if billed:
            raise UserError(_(
                "Commission on %(inv)s is already on commission bill %(bill)s. Cancel or credit that bill "
                "first (Accounting > Vendors > Bills), then try again.",
                inv=', '.join(billed.invoice_id.mapped('name')),
                bill=', '.join(billed.mapped(lambda l: l._x_active_bill().name or _('(draft)')))))
        self._combine_unbook()
        return super().unlink()

    # -------------------------------------------------------------- billing
    def _combine_bill(self, ref=False):
        """Create one commission bill per agent for these lines.

        Lines not yet booked (e.g. invoices posted before this module) are
        booked first, dated today, and an agent without a party gets one -
        all only because a user asked for the bill."""
        not_booked = self.filtered(lambda l: l._x_state() == 'not_booked' and l.payment_state != 'paid'
                                   and not l.currency_id.is_zero(l.commission_amount))
        if not_booked:
            not_booked.agent_id.filtered(lambda a: not a.partner_id).action_combine_create_party()
            not_booked._combine_book(date=fields.Date.context_today(self))
        lines = self.filtered(lambda l: l._x_state() == 'unbilled')
        if not lines:
            if self.filtered(lambda l: l._x_state() in ('billed', 'paid')):
                raise UserError(_('This commission is already billed (see the Commission button).'))
            raise UserError(_('There is no commission to bill.'))
        bills = self.env['account.move']
        groups = defaultdict(lambda: self.env['combine001.commission.line'])
        for line in lines:
            groups[(line.company_id or self.env.company, line.agent_id)] |= line
        for (company, agent), group in groups.items():
            total = sum(group.mapped('commission_amount'))
            if company.currency_id.compare_amounts(total, 0.0) <= 0:
                raise UserError(_('Commission to bill for %s is zero or negative - nothing to bill.', agent.name))
            _expense, accrual, _journal = company._combine_commission_setup(raise_if_missing=True)
            today = fields.Date.context_today(self)
            bill = self.env['account.move'].with_company(company).create({
                'move_type': 'in_invoice',
                'partner_id': agent.partner_id.id,
                'journal_id': company._combine_purchase_journal().id,
                'invoice_date': today,
                'date': today,
                'ref': ref or _('Commission - %s', ', '.join(sorted(set(group.invoice_id.mapped('name'))))),
                'x_is_commission_bill': True,
            })
            for cl in group.sorted(lambda l: (l.date or today, l.id)):
                before = bill.invoice_line_ids
                bill.write({'invoice_line_ids': [Command.create({
                    'name': _('Commission %(rate)s%% on %(inv)s - %(so)s - %(cust)s - %(item)s', rate='{:g}'.format(cl.rate),
                              inv=cl.invoice_id.name, so=cl.sale_order_id.name, cust=cl.partner_id.name or '',
                              item=cl.product_id.display_name or ''),
                    'account_id': accrual.id,
                    'quantity': 1.0,
                    'price_unit': cl.commission_amount,
                    'tax_ids': [Command.clear()],
                })]})
                cl.sudo().x_bill_line_id = (bill.invoice_line_ids - before)[:1]
            bill.message_post(body=_('Commission bill for %(agent)s - %(n)s commission line(s).',
                                     agent=agent.name, n=len(group)))
            bills |= bill
        return bills

    @api.model
    def _action_open_bills(self, bills):
        action = self.env['ir.actions.act_window']._for_xml_id('account.action_move_in_invoice_type')
        if len(bills) == 1:
            action.update({'views': [(False, 'form')], 'res_id': bills.id, 'view_mode': 'form'})
        else:
            action['domain'] = [('id', 'in', bills.ids)]
        return action


class AccountMove(models.Model):
    _inherit = 'account.move'

    x_commission_kind = fields.Selection([('booking', 'Commission booking'), ('reversal', 'Commission reversal')],
                                         readonly=True, copy=False, string='Commission Entry')
    x_is_commission_bill = fields.Boolean(readonly=True, copy=False, string='Commission Bill')
    x_commission_line_count = fields.Integer(compute='_compute_x_commission_info', string='Commission')
    x_can_bill_commission = fields.Boolean(compute='_compute_x_commission_info')
    x_can_book_commission = fields.Boolean(compute='_compute_x_commission_info')
    x_commission_wht_rate = fields.Float(compute='_compute_x_commission_wht', string='Withholding Rate (%)')
    x_commission_wht_amount = fields.Monetary(compute='_compute_x_commission_wht', string='Withholding Tax')

    def _x_commission_lines(self):
        CL = self.env['combine001.commission.line'].sudo()
        if self.x_is_commission_bill:
            return CL.search([('x_bill_line_id.move_id', '=', self.id)])
        return CL.search([('invoice_id', '=', self.id)])

    def _compute_x_commission_info(self):
        for move in self:
            lines = move._x_commission_lines() if move.id and (
                move.x_is_commission_bill or move.move_type in ('out_invoice', 'out_refund')) else False
            states = {l._x_state() for l in lines} if lines else set()
            move.x_commission_line_count = len(lines) if lines else 0
            posted_sale = move.state == 'posted' and move.move_type in ('out_invoice', 'out_refund')
            open_lines = lines and any(
                l._x_state() == 'unbilled' or (l._x_state() == 'not_booked' and l.payment_state != 'paid')
                for l in lines)
            missing = posted_sale and not lines and move._x_has_agent()
            move.x_can_bill_commission = posted_sale and bool(open_lines or missing)
            move.x_can_book_commission = posted_sale and bool(lines) and any(
                l._x_state() == 'not_booked' and l.payment_state != 'paid' for l in lines)

    @api.depends('partner_id', 'invoice_date', 'amount_total', 'x_is_commission_bill')
    def _compute_x_commission_wht(self):
        Rate = self.env['combine001.withholding.rate']
        for move in self:
            rate = 0.0
            if move.x_is_commission_bill and move.partner_id:
                rate = Rate._combine001_get_effective_rate(
                    move.partner_id, 'purchase', move.invoice_date or fields.Date.context_today(move)) or 0.0
            move.x_commission_wht_rate = rate
            move.x_commission_wht_amount = move.currency_id.round(move.amount_total * rate / 100.0) if rate else 0.0

    # ------------------------------------------------------------- posting
    def _post(self, soft=True):
        posted = super()._post(soft)
        for move in posted.filtered(lambda m: m.move_type in ('out_invoice', 'out_refund')):
            move._combine_commission_on_post()
        return posted

    def _combine_commission_on_post(self):
        """Create this invoice's commission lines (if combine001 has not yet)
        and book the ones created now. Lines that already existed are left
        exactly as they are."""
        self.ensure_one()
        CL = self.env['combine001.commission.line'].sudo()
        existing = CL.search([('invoice_id', '=', self.id)])
        if self.move_type == 'out_invoice':
            self.sudo()._combine001_create_commission_lines()
        else:
            self.sudo()._combine_create_refund_commission_lines()
        new_lines = CL.search([('invoice_id', '=', self.id)]) - existing
        if not new_lines:
            return
        skipped = new_lines._combine_book()
        if skipped:
            self.message_post(body=_(
                "Commission not booked in the accounts: agent %s has no party. Open the agent "
                "(Combine001 > Configuration > Commission Agents), click Create Party, then click "
                "Book Commission on this invoice.", ', '.join(skipped.mapped('name'))))

    def _combine_create_refund_commission_lines(self):
        """Credit note against a contract with an agent: negative commission."""
        self.ensure_one()
        CL = self.env['combine001.commission.line'].sudo()
        for line in self.invoice_line_ids:
            sale_line = line.sale_line_ids[:1]
            order = sale_line.order_id
            if not sale_line or not order.commission_agent_id:
                continue
            if CL.search_count([('invoice_line_id', '=', line.id)]):
                continue
            base = order.commission_base or order.commission_agent_id.default_base
            rate = order.commission_rate or order.commission_agent_id.default_rate
            base_amount = line.quantity if base == 'quantity' else line.price_subtotal
            CL.create({
                'agent_id': order.commission_agent_id.id,
                'sale_order_id': order.id,
                'sale_line_id': sale_line.id,
                'invoice_id': self.id,
                'invoice_line_id': line.id,
                'base_amount': -base_amount,
                'rate': rate,
                'commission_amount': -base_amount * (rate or 0.0) / 100.0,
            })

    def button_draft(self):
        sales = self.filtered(lambda m: m.state == 'posted' and m.move_type in ('out_invoice', 'out_refund'))
        lines = self.env['combine001.commission.line'].sudo().search([('invoice_id', 'in', sales.ids)]) \
            if sales else self.env['combine001.commission.line']
        billed = lines.filtered(lambda l: l._x_active_bill())
        if billed:
            raise UserError(_(
                "%(inv)s cannot go back to draft: its commission is already on commission bill %(bill)s. "
                "Cancel or credit that bill first.",
                inv=', '.join(billed.invoice_id.mapped('name')),
                bill=', '.join(billed.mapped(lambda l: l._x_active_bill().name or _('(draft)')))))
        res = super().button_draft()
        # remove only what this module booked; the invoice re-books when posted again
        lines.filtered(lambda l: l.exists() and l.x_accrual_move_id).unlink()
        return res

    # ------------------------------------------------------------- buttons
    def _x_has_agent(self):
        self.ensure_one()
        return bool(self.invoice_line_ids.sale_line_ids.order_id.filtered('commission_agent_id'))

    def action_combine_bill_commission(self):
        """Bill Commission - works for any posted sales invoice, including
        ones posted before this module: missing commission lines are
        created, unbooked commission is booked (today), then billed."""
        self.ensure_one()
        if self.state != 'posted' or self.move_type not in ('out_invoice', 'out_refund'):
            raise UserError(_('Commission is billed from a posted sales invoice.'))
        if not self._x_commission_lines():
            if not self._x_has_agent():
                raise UserError(_('The contract of %s has no commission agent.', self.name))
            if self.move_type == 'out_invoice':
                self.sudo()._combine001_create_commission_lines()
            else:
                self.sudo()._combine_create_refund_commission_lines()
        bills = self._x_commission_lines()._combine_bill()
        return self.env['combine001.commission.line']._action_open_bills(bills)

    def action_combine_book_commission(self):
        self.ensure_one()
        if not self.env.user.has_group('account.group_account_manager'):
            raise UserError(_('Only a Finance Manager can book commission of an earlier invoice.'))
        lines = self._x_commission_lines().filtered(lambda l: l._x_state() == 'not_booked')
        lines.agent_id.filtered(lambda a: not a.partner_id).action_combine_create_party()
        skipped = lines._combine_book(date=fields.Date.context_today(self))
        if skipped:
            raise UserError(_(
                "Agent %s has no party. Open the agent (Combine001 > Configuration > Commission Agents), "
                "click Create Party, then try again.", ', '.join(skipped.mapped('name'))))
        return True

    def action_combine_view_commission(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('combine001.action_commission_line')
        action['domain'] = [('id', 'in', self._x_commission_lines().ids)]
        action['context'] = {}
        return action


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def write(self, vals):
        keys = ('commission_agent_id', 'commission_rate', 'commission_base')
        if not any(k in vals for k in keys):
            return super().write(vals)

        def changed(order):
            for k in keys:
                if k not in vals:
                    continue
                cur = order[k]
                cur = cur.id if isinstance(cur, models.BaseModel) else cur
                if (cur or False) != (vals[k] or False):
                    return True
            return False

        orders = self.filtered(lambda o: o.state == 'sale' and changed(o))
        CL = self.env['combine001.commission.line'].sudo()
        lines = CL.search([('sale_order_id', 'in', orders.ids)]) if orders else CL
        billed = lines.filtered(lambda l: l._x_active_bill())
        if billed:
            raise UserError(_(
                "The commission agent / rate of %(so)s cannot change: its commission is already billed on "
                "%(bill)s. Cancel or credit that bill first.",
                so=', '.join(billed.sale_order_id.mapped('name')),
                bill=', '.join(billed.mapped(lambda l: l._x_active_bill().name or _('(draft)')))))
        res = super().write(vals)
        if orders:
            # what this module booked is redone with the new agent / rate;
            # lines from before this module stay as they are
            lines.filtered('x_accrual_move_id').unlink()
            for order in orders:
                for invoice in order.invoice_ids.filtered(
                        lambda m: m.state == 'posted' and m.move_type in ('out_invoice', 'out_refund')):
                    invoice._combine_commission_on_post()
        return res
