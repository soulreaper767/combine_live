from odoo import fields, models


class PartnerStatementWizard(models.TransientModel):
    """Entry point for the corporate-formatted Partner Statement PDF -
    deliberately its own wizard/report, not a button bolted onto the
    native Partner Ledger (that report's print output is shared with
    every other account_reports report and can't have its own layout -
    see report/partner_statement_report.py docstring)."""
    _name = 'partner.ledger.statement.wizard'
    _description = 'Partner Statement - print options'

    partner_id = fields.Many2one('res.partner', string='Partner', required=True)
    date_from = fields.Date(string='From', required=True,
                             default=lambda self: fields.Date.context_today(self).replace(month=1, day=1))
    date_to = fields.Date(string='To', required=True, default=fields.Date.context_today)

    def action_print(self):
        self.ensure_one()
        return self.env.ref('partner_ledger_qty.action_report_partner_statement').report_action(self)
