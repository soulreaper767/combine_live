import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """End of update: bring back the user-created heads the party merge took
    (lines put back exactly from the merge record), and stop the daily job
    that archived settled receivable / payable heads."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    cron = env.ref("partner_ledger_qty.cron_archive_settled_party_accounts", raise_if_not_found=False)
    if cron:
        cron.active = False
    for company in env["res.company"].search([]):
        log = company.with_company(company)._restore_user_heads()
        _logger.info("user-created heads restored (%s): %s", company.name, log)
