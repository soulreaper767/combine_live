from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools import SQL


class AccountPartnerLedgerReportHandler(models.AbstractModel):
    """Adds a 'Qty' column to the native Partner Ledger report, showing
    the invoiced quantity on Sales Invoice lines only - blank for every
    other line type (bills, payments, misc entries, credit notes).

    The row the Partner Ledger shows for an invoice is its receivable/
    payable line (the balancing entry against the partner's control
    account) - account_move_line.quantity on THAT line is always 0,
    Odoo never puts a meaningful quantity there. The real quantity lives
    on the invoice's own product lines (display_type='product'), a
    different account_move_line row on the same move - so the value
    here is the SUM of those sibling lines' quantities, not this row's
    own (always-zero) quantity. Confirmed by testing: an early version
    that read account_move_line.quantity directly showed 0 for every
    invoice.

    Uses account_reports' own documented extension hook
    (_get_additional_column_aml_values, see
    account_reports/models/account_partner_ledger.py - "This method is
    intended to be overridden by other modules to add custom fields to
    the partner ledger query") instead of touching the core report file
    or its XML - the base report, its other columns and every other
    report built on this engine are untouched."""
    _inherit = 'account.partner.ledger.report.handler'

    def _get_additional_column_aml_values(self):
        base = super()._get_additional_column_aml_values()
        return SQL(
            "%s CASE WHEN account_move.move_type = 'out_invoice' THEN ("
            "    SELECT SUM(aml_qty.quantity) FROM account_move_line aml_qty "
            "    WHERE aml_qty.move_id = account_move_line.move_id "
            "      AND aml_qty.display_type = 'product'"
            ") ELSE NULL END AS quantity,",
            base,
        )

    def action_print_partner_statement(self, options):
        """Handler for the 'Statement PDF' button added to this report's
        own toolbar (see AccountReportPartnerStatementButton below) -
        account_reports' dispatch_report_action() looks for the action
        name on the report's custom handler model FIRST, before falling
        back to account.report itself, so defining it here (rather than
        on account.report) scopes it to only ever run for this report.

        Requires the report's own Partner filter to be narrowed to
        exactly one partner first - this report (unlike the native
        Partner Ledger) is always about one specific partner's
        statement, and options['partner_ids'] is exactly how that
        filter already communicates the selection."""
        partner_ids = options.get('partner_ids') or []
        if len(partner_ids) != 1:
            raise UserError(_(
                "Filter this report to exactly one partner first (use the "
                "Partner filter above), then click Statement PDF again."
            ))
        date_options = options.get('date') or {}
        wizard = self.env['partner.ledger.statement.wizard'].create({
            'partner_id': partner_ids[0],
            'date_from': date_options.get('date_from') or fields.Date.context_today(self).replace(month=1, day=1),
            'date_to': date_options.get('date_to') or fields.Date.context_today(self),
        })
        return wizard.action_print()


class AccountReportPartnerStatementButton(models.Model):
    """Adds the 'Statement PDF' button itself to the Partner Ledger
    report's own toolbar, right next to the native PDF/XLSX buttons -
    _init_options_buttons is defined on account.report (shared by every
    report on this engine), so the override is scoped to only the
    Partner Ledger report by checking the report's own id; every other
    report's button bar is built by the untouched super() call alone."""
    _inherit = 'account.report'

    def _init_options_buttons(self, options, previous_options):
        super()._init_options_buttons(options, previous_options)
        if self == self.env.ref('account_reports.partner_ledger_report'):
            options['buttons'].append({
                'name': _('Statement PDF'),
                'action': 'action_print_partner_statement',
                'sequence': 15,
                'always_show': True,
            })
