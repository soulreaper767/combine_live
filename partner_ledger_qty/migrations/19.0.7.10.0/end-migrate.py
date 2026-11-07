import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Runs at the END of the update (all modules loaded, so every field default exists -
    e.g. account_asset's required create_asset on accounts).
    Four party control accounts (customers, vendors, customer advances,
    vendor advances): created if missing, made the defaults, every party
    pointed to them, other party accounts archived once nothing is open.
    No journal entry is edited."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    for company in env["res.company"].search([]):
        log = company.with_company(company)._setup_party_control_accounts()
        _logger.info("party control accounts setup (%s): %s", company.name, log)
