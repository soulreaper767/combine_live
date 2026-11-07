import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Automatic purchase / stores ledger entries from now on: adds the GRN
    Clearing and Stores stock accounts, points the Vendors location at GRN
    Clearing, makes raw material + stores categories perpetual with average
    cost while keeping every item's current cost. Only fills what is empty;
    no existing document, entry, stock or cost is changed."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    for company in env['res.company'].search([]):
        log = env['stock.location'].with_company(company).with_context(allowed_company_ids=[company.id])._combine_setup_purchase_accounting()
        _logger.info('combine_stores purchase accounting setup (%s): %s', company.name, log)
