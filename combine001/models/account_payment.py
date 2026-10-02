from odoo import _, api, fields, models

from .combine001_constants import WHT_PURCHASE_PAYABLE_CODE, WHT_SALE_RECEIVABLE_CODE


class AccountPayment(models.Model):
    """Withholding tax automation on payments (follow-up request on top
    of the BRD): 'purchase' direction (paying a Vendor) withholds tax
    from what WE pay; 'sale' direction (receiving from a Customer)
    tracks what the CUSTOMER is expected to withhold from what they pay
    US. Both post through Odoo's own native
    `_prepare_move_withholding_lines` hook (core `account`, a documented
    no-op stub existing specifically for this purpose) so the liquidity
    line is correctly reduced by the withheld amount while the
    counterpart (payable/receivable) line still clears the FULL invoice
    amount - the standard "payment net of tax withheld" mechanic,
    without duplicating any of Odoo's own balancing logic.
    """
    _inherit = 'account.payment'

    x_wht_applicable = fields.Boolean(
        string='Is Withholding Applicable', tracking=True,
        help='When set, a withholding-tax line is posted on this payment, reducing what actually '
             'moves through the bank/cash account while the invoice/bill it settles is still cleared '
             'in full. Defaulted automatically when registering payment against a GST-bearing bill '
             '(purchase side); always review before confirming.')
    x_wht_rate = fields.Float(
        string='Withholding Rate (%)',
        help='Defaulted from Combine001 > Taxation > Withholding Tax Rates for this partner/date '
             '(the exemption\'s reduced rate if one applies) - override here if this specific '
             'payment differs from the configured rate.')
    x_wht_amount = fields.Monetary(compute='_compute_x_wht_amount', store=True, string='Withholding Amount')
    x_wht_account_id = fields.Many2one(
        'account.account', string='Withholding Account',
        help='Purchase side: Withholding Tax Payable (liability). Sale side: Advance Income Tax / '
             'Withholding Tax Receivable (asset). Defaulted from the Chart of Accounts.')

    # -- Sale-side variance (BRD follow-up: did the Customer withhold the
    # right amount?) - always computed fresh from the rate table for
    # this payment's own date, independent of whatever x_wht_rate/
    # x_wht_applicable actually ended up being entered, so the variance
    # report can show "what should have happened" vs "what did". -------
    x_wht_expected_rate = fields.Float(compute='_compute_x_wht_expected', store=True, string='Expected Rate (%)')
    x_wht_expected_amount = fields.Monetary(compute='_compute_x_wht_expected', store=True, string='Expected Withholding')
    x_wht_variance = fields.Monetary(compute='_compute_x_wht_expected', store=True, string='Variance (Actual - Expected)')

    @api.depends('amount', 'x_wht_rate', 'x_wht_applicable')
    def _compute_x_wht_amount(self):
        for pay in self:
            pay.x_wht_amount = (pay.amount * pay.x_wht_rate / 100.0) if pay.x_wht_applicable else 0.0

    @api.depends('partner_id', 'payment_type', 'date', 'amount', 'x_wht_amount')
    def _compute_x_wht_expected(self):
        Rate = self.env['combine001.withholding.rate']
        for pay in self:
            if pay.payment_type == 'inbound' and pay.partner_id and pay.date:
                pay.x_wht_expected_rate = Rate._combine001_get_effective_rate(pay.partner_id, 'sale', pay.date)
                pay.x_wht_expected_amount = pay.amount * pay.x_wht_expected_rate / 100.0
                pay.x_wht_variance = pay.x_wht_amount - pay.x_wht_expected_amount
            else:
                pay.x_wht_expected_rate = 0.0
                pay.x_wht_expected_amount = 0.0
                pay.x_wht_variance = 0.0

    @api.onchange('partner_id', 'payment_type', 'date', 'amount')
    def _onchange_combine001_wht(self):
        for pay in self:
            if not pay.partner_id or pay.payment_type not in ('inbound', 'outbound'):
                continue
            direction = 'purchase' if pay.payment_type == 'outbound' else 'sale'
            pay.x_wht_rate = self.env['combine001.withholding.rate']._combine001_get_effective_rate(
                pay.partner_id, direction, pay.date or fields.Date.context_today(pay))
            pay.x_wht_account_id = pay._combine001_get_wht_account(direction)

    def _combine001_get_wht_account(self, direction):
        code = WHT_PURCHASE_PAYABLE_CODE if direction == 'purchase' else WHT_SALE_RECEIVABLE_CODE
        return self.env['account.account'].search([
            ('company_ids', 'in', (self.company_id or self.env.company).id), ('code', '=', code),
        ], limit=1)

    @api.model
    def _combine001_default_wht_vals(self, partner_id, payment_type, pay_date, moves):
        """Used both by the account.payment.register wizard override
        below (the normal 'Register Payment' flow, where the source
        bill/invoice is known) and available for any other programmatic
        payment creation that wants the same defaults."""
        if payment_type not in ('inbound', 'outbound') or not partner_id:
            return {}
        direction = 'purchase' if payment_type == 'outbound' else 'sale'
        partner = self.env['res.partner'].browse(partner_id)
        rate = self.env['combine001.withholding.rate']._combine001_get_effective_rate(partner, direction, pay_date)
        applicable = direction == 'purchase' and bool(moves) and any(
            move._combine001_has_gst_charged() for move in moves
        )
        account = self._combine001_get_wht_account(direction)
        return {
            'x_wht_applicable': applicable,
            'x_wht_rate': rate,
            'x_wht_account_id': account.id if account else False,
        }

    def _prepare_move_withholding_lines(self, default_values):
        self.ensure_one()
        if not self.x_wht_applicable or not self.x_wht_amount or not self.x_wht_account_id:
            return super()._prepare_move_withholding_lines(default_values)

        sign = -1 if self.payment_type == 'outbound' else 1
        amount_currency = sign * self.x_wht_amount
        balance = self.currency_id._convert(amount_currency, self.company_id.currency_id, self.company_id, self.date)
        label = _("Withholding Tax @ %(rate)s%%", rate=self.x_wht_rate)
        return [{
            'name': label,
            'date_maturity': self.date,
            'partner_id': self.partner_id.id,
            'account_id': self.x_wht_account_id.id,
            'currency_id': self.currency_id.id,
            'balance': balance,
            'amount_currency': amount_currency,
        }]


class AccountPaymentRegister(models.TransientModel):
    """The normal, day-to-day path for creating a payment against a
    posted bill/invoice - the wizard already knows which move(s) are
    being settled, which the plain account.payment onchange above
    cannot (a bare 'Accounting > Payments > New' has no invoice
    context), so this is where the 'applicable by default when the
    bill/invoice carries GST' rule (purchase side) is actually applied."""
    _inherit = 'account.payment.register'

    def _create_payment_vals_from_wizard(self, batch_result):
        # Single-invoice registration (the common case) goes through
        # this method.
        vals = super()._create_payment_vals_from_wizard(batch_result)
        vals.update(self.env['account.payment']._combine001_default_wht_vals(
            partner_id=vals.get('partner_id'),
            payment_type=vals.get('payment_type'),
            pay_date=vals.get('date') or fields.Date.context_today(self),
            moves=batch_result['lines'].move_id,
        ))
        return vals

    def _create_payment_vals_from_batch(self, batch_result):
        # A multi-invoice, ungrouped payment goes through THIS method
        # instead - _create_payments() picks one or the other depending
        # on edit_mode, never both, so the defaults must be applied here
        # too or they silently never apply for that case.
        vals = super()._create_payment_vals_from_batch(batch_result)
        vals.update(self.env['account.payment']._combine001_default_wht_vals(
            partner_id=vals.get('partner_id'),
            payment_type=vals.get('payment_type'),
            pay_date=vals.get('date') or fields.Date.context_today(self),
            moves=batch_result['lines'].move_id,
        ))
        return vals
