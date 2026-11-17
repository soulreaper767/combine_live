from datetime import date

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

TAX_TYPES = [('gst', 'Sales Tax (GST)'), ('income_tax', 'Income Tax'), ('pra', 'PRA (Services)')]
STATUSES = [('registered', 'Registered'), ('unregistered', 'Unregistered'),
            ('filer', 'Filer'), ('non_filer', 'Non-Filer')]
VALID = {'gst': ('registered', 'unregistered'), 'income_tax': ('filer', 'non_filer'),
         'pra': ('registered', 'unregistered')}
PARTNER_FIELD = {'gst': 'x_gst_status', 'income_tax': 'x_income_tax_status', 'pra': 'x_pra_status'}


class TaxStatusPeriod(models.Model):
    """Per-party, dated registration status - same idea as the Withholding Tax Rates."""
    _name = 'combine.tax.status.period'
    _description = 'Tax Registration Status Period'
    _order = 'partner_id, tax_type, date_from desc'

    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)
    partner_id = fields.Many2one('res.partner', required=True, string='Customer / Vendor', index=True,
                                 ondelete='cascade', domain=[('parent_id', '=', False)])
    tax_type = fields.Selection(TAX_TYPES, required=True, default='gst', string='Tax')
    status = fields.Selection(STATUSES, required=True)
    date_from = fields.Date(required=True)
    date_to = fields.Date(help='Leave empty for open-ended (still in effect).')
    reference = fields.Char(string='Certificate / Reference')

    @api.constrains('tax_type', 'status')
    def _check_status(self):
        for rec in self:
            if rec.status not in VALID[rec.tax_type]:
                raise ValidationError(_('%(tax)s status must be %(ok)s.', tax=dict(TAX_TYPES)[rec.tax_type],
                                        ok=' / '.join(dict(STATUSES)[s] for s in VALID[rec.tax_type])))

    @api.constrains('date_from', 'date_to')
    def _check_date_range(self):
        for rec in self:
            if rec.date_to and rec.date_to < rec.date_from:
                raise ValidationError(_('The end date cannot be before the start date.'))

    @api.constrains('partner_id', 'tax_type', 'date_from', 'date_to', 'company_id')
    def _check_no_overlap(self):
        for rec in self:
            siblings = self.search([('id', '!=', rec.id), ('company_id', '=', rec.company_id.id),
                                    ('partner_id', '=', rec.partner_id.id), ('tax_type', '=', rec.tax_type)])
            a_from, a_to = rec.date_from, rec.date_to or date.max
            for sib in siblings:
                if a_from <= (sib.date_to or date.max) and sib.date_from <= a_to:
                    raise ValidationError(_(
                        '%(partner)s already has a %(tax)s status covering an overlapping period (%(f)s - %(t)s).',
                        partner=rec.partner_id.display_name, tax=dict(TAX_TYPES)[rec.tax_type],
                        f=sib.date_from, t=sib.date_to or _('open-ended')))

    @api.model
    def _combine_statuses_at(self, partner, on_date, company=None):
        """{'x_gst_status': .., 'x_income_tax_status': .., 'x_pra_status': ..} for this party on this date;
        a status with no period covering the date comes from the party's Tax Info tab."""
        partner = partner.commercial_partner_id
        if not partner:
            return {}
        company = company or self.env.company
        on_date = on_date or fields.Date.context_today(self)
        periods = self.sudo().search([('partner_id', '=', partner.id), ('company_id', '=', company.id),
                                      ('date_from', '<=', on_date), '|', ('date_to', '=', False),
                                      ('date_to', '>=', on_date)])
        out = {}
        for tax_type, fname in PARTNER_FIELD.items():
            period = periods.filtered(lambda p: p.tax_type == tax_type)[:1]
            out[fname] = period.status if period else partner[fname]
        return out


class ResPartner(models.Model):
    _inherit = 'res.partner'

    x_tax_status_period_ids = fields.One2many('combine.tax.status.period', 'partner_id', string='Status by Date')
