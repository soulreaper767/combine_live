from odoo import fields, models


class PartnerStatementWizard(models.TransientModel):
    """Entry point: Accounting > Reporting > Partner Ledger Print (a
    dedicated menu item, not a button bolted onto the native Partner
    Ledger report's own toolbar - that report's Partner filter turned
    out hard to find/use in practice, so this is a plain, simple dialog
    instead: pick a partner, pick a date range, click Generate Report."""
    _name = 'partner.ledger.statement.wizard'
    _description = 'Partner Statement - print options'

    partner_id = fields.Many2one('res.partner', string='Partner', required=True)
    date_from = fields.Date(string='From', required=True,
                             default=lambda self: fields.Date.context_today(self).replace(month=1, day=1))
    date_to = fields.Date(string='To', required=True, default=fields.Date.context_today)

    def action_print(self):
        self.ensure_one()
        return self.env.ref('partner_ledger_qty.action_report_partner_statement').report_action(self)
