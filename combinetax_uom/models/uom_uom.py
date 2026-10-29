import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# Units that must exist under exactly this name (Master-Child Sync
# matches units by name; the rest are the stores / packing setup).
REQUIRED_UNITS = ['Bag', 'Box', 'Set', 'Packet', 'Bottle', 'Pair', 'Gallon', 'Roll', 'Coil']

# name -> (stock valuation account code, account name if it has to be created)
REQUIRED_CATEGORIES = {
    'Stores & Spares': ('3.07.01.0001', 'STORES AND SPARES'),
    'Packing Material': ('3.07.01.0002', 'PACKING MATERIAL'),
}
COST_METHOD = 'average'
PRICE_DIGITS = 4


class UomUom(models.Model):
    _inherit = 'uom.uom'

    @api.model
    def _combinetax_ensure_units(self):
        """Create-if-missing only: an existing unit, category, account or a
        higher precision is never changed."""
        Uom = self.with_context(active_test=False)
        for name in REQUIRED_UNITS:
            if not Uom.search_count([('name', '=', name)]):
                Uom.create({'name': name})

        Category = self.env['product.category']
        for name, (code, account_name) in REQUIRED_CATEGORIES.items():
            if Category.search_count([('name', '=', name)]):
                continue
            category = Category.create({'name': name})
            for company in self.env['res.company'].search([]):
                category.with_company(company).write({
                    'property_cost_method': COST_METHOD,
                    'property_valuation': 'real_time',
                    'property_stock_valuation_account_id': self._combinetax_account(company, code, account_name).id,
                })

        precision = self.env.ref('product.decimal_price', raise_if_not_found=False)
        if precision and precision.digits < PRICE_DIGITS:
            precision.digits = PRICE_DIGITS

    @api.model
    def _combinetax_account(self, company, code, name):
        Account = self.env['account.account'].with_company(company)
        account = Account.search([('company_ids', 'in', company.id), ('code', '=', code)], limit=1)
        if not account:
            account = Account.create({
                'code': code, 'name': name, 'account_type': 'asset_current',
                'company_ids': [(6, 0, company.ids)],
            })
            _logger.info("combinetax_uom: created stock valuation account %s %s", code, name)
        return account
