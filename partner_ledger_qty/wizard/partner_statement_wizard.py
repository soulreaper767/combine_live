from odoo import fields, models


class PartnerStatementWizard(models.TransientModel):
    """Carries the one partner + date range a Partner Statement print
    needs. No form view of its own - the Partner Ledger report's
    'Statement PDF' button (see models/account_partner_ledger_report.py)
    creates one of these directly from that report's own Partner/date
    filters and immediately calls action_print(), with no dialog shown.
    The report (own query/template, not a reskin of the native Partner
    Ledger - see report/partner_statement_report.py) is still a
    completely different document, so a dedicated carrier record is
    still needed for the print action to be bound to."""
    _name = 'partner.ledger.statement.wizard'
    _description = 'Partner Statement - print options'

    partner_id = fields.Many2one('res.partner', string='Partner', required=True)
    date_from = fields.Date(string='From', required=True,
                             default=lambda self: fields.Date.context_today(self).replace(month=1, day=1))
    date_to = fields.Date(string='To', required=True, default=fields.Date.context_today)

    def action_print(self):
        self.ensure_one()
        return self.env.ref('partner_ledger_qty.action_report_partner_statement').report_action(self)
