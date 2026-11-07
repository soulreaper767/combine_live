import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """End of update (all modules loaded): put the four control accounts on
    every existing party line - posted, draft, cancelled - and payment,
    recording each change first so it can be reversed; then archive the old
    party accounts. Amounts, dates, numbers, parties, reconciliations and
    open amounts are not touched."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    for company in env["res.company"].search([]):
        if company.x_customer_control_id:
            log = company.with_company(company)._remap_party_lines_to_controls()
            _logger.info("party lines remapped (%s): %s", company.name, log)
