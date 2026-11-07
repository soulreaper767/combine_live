import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """End of update: lines on the old (non-party) Advances to Supplier
    account carry a party but never reached its ledger - move them to
    3.09.16 Advances to Suppliers (recorded first, reversible), archive the
    old account. Only the account changes."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    for company in env["res.company"].search([]):
        if company.x_vendor_advance_id:
            log = company.with_company(company)._remap_advance_lines()
            _logger.info("advance lines moved (%s): %s", company.name, log)
