from datetime import date

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class WithholdingRate(models.Model):
    """Per-partner, time-ranged withholding tax rate. Rates change over
    time and a partner can hold an exemption certificate for a period
    (with its own, possibly 0%, reduced rate) - see models/account_payment.py
    for how a payment resolves the applicable rate/exemption for its own
    date and uses it to post the actual withholding accounting entry.

    'purchase' = the rate WE withhold when paying this Vendor.
    'sale' = the rate THIS CUSTOMER is expected to withhold when paying
    us - tracked from the company's own side since we don't control the
    customer's books. See the WHT Variance report (an account.payment
    action) for comparing this expected rate against what a customer
    actually withheld on a given payment.
    """
    _name = 'combine001.withholding.rate'
    _description = 'Withholding Tax Rate'
    _order = 'partner_id, direction, date_from desc'

    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)
    partner_id = fields.Many2one('res.partner', required=True, string='Vendor / Customer')
    direction = fields.Selection([
        ('purchase', 'Purchase (we withhold from this Vendor)'),
        ('sale', 'Sale (this Customer withholds from us)'),
    ], required=True)
    date_from = fields.Date(required=True)
    date_to = fields.Date(help='Leave empty for open-ended (still in effect).')
    rate = fields.Float(string='Standard Rate (%)', required=True)
    is_exempt = fields.Boolean(string='Exempt in this Period')
    exempt_rate = fields.Float(
        string='Reduced Rate During Exemption (%)',
        help='Rate actually applied while exempt - 0 for a full exemption, or a lower-than-standard '
             'reduced rate per the exemption certificate.')
    reason = fields.Char(string='Exemption Certificate / Reason')

    @api.constrains('partner_id', 'direction', 'date_from', 'date_to')
    def _check_no_overlap(self):
        for rec in self:
            siblings = self.search([
                ('id', '!=', rec.id),
                ('company_id', '=', rec.company_id.id),
                ('partner_id', '=', rec.partner_id.id),
                ('direction', '=', rec.direction),
            ])
            a_from, a_to = rec.date_from, rec.date_to or date.max
            for sib in siblings:
                b_from, b_to = sib.date_from, sib.date_to or date.max
                if a_from <= b_to and b_from <= a_to:
                    raise ValidationError(_(
                        "%(partner)s already has a %(direction)s withholding rate covering an "
                        "overlapping period (%(other_from)s - %(other_to)s).",
                        partner=rec.partner_id.display_name, direction=dict(
                            rec._fields['direction'].selection)[rec.direction],
                        other_from=sib.date_from, other_to=sib.date_to or _('open-ended'),
                    ))

    @api.constrains('date_from', 'date_to')
    def _check_date_range(self):
        for rec in self:
            if rec.date_to and rec.date_to < rec.date_from:
                raise ValidationError(_('The end date cannot be before the start date.'))

    @api.model
    def _combine001_get_effective_rate(self, partner, direction, for_date):
        """Resolve the rate applicable to `partner` for `direction` on
        `for_date`: the exemption's reduced rate if exempt in that
        period, else the period's standard rate, else 0.0 (no
        withholding) if nothing is configured for that partner/date."""
        rate = self.search([
            ('company_id', '=', self.env.company.id),
            ('partner_id', '=', partner.id),
            ('direction', '=', direction),
            ('date_from', '<=', for_date),
            '|', ('date_to', '=', False), ('date_to', '>=', for_date),
        ], limit=1)
        if not rate:
            return 0.0
        return rate.exempt_rate if rate.is_exempt else rate.rate
