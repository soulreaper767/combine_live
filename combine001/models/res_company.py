import logging

from odoo import api, models

from .combine001_constants import (
    GST_SAVING_ASSET_CODE, GST_SAVING_EQUITY_CODE, WHT_SALE_RECEIVABLE_CODE,
)

_logger = logging.getLogger(__name__)

# --- GST Saving / Withholding accounts ---------------------------------
# combine_live is the customizations-only variant of this module: it
# does NOT import Combine Spinning's real Chart of Accounts, opening
# trial balance, Customers/Vendors or product catalog (see
# combine001/data/import/ in the `combine001` repo for that - this repo
# deliberately has no data/import/ directory at all). This live server
# is expected to already have the company's real CoA in place (same
# numbering scheme the full-import repo uses - these codes were
# originally chosen by searching that real CoA for genuinely unused
# slots; see that repo's README for the full reasoning). The 3
# structural accounts below are forward-looking accounts this module's
# GST Saving / Withholding Tax features need to exist regardless of how
# the rest of the CoA was set up; the Finished Goods/Socks/Lycra
# accounts from the full-import variant are NOT needed here since this
# variant doesn't import that product catalog either.
_STRUCTURAL_GROUPS = [
    ('1.09', 'GST SAVING RESERVE'),
    ('3.13', 'GST SAVING'),
]
_STRUCTURAL_ACCOUNTS = [
    # code, name, account_type
    (GST_SAVING_ASSET_CODE, 'GST SAVING', 'asset_current'),
    (GST_SAVING_EQUITY_CODE, 'GST SAVING RESERVE', 'equity'),
    # Withholding tax, sale-side receivable only - the purchase-side
    # payable reuses an existing leaf account already in the real CoA
    # (see combine001_constants.py, WHT_PURCHASE_PAYABLE_CODE) and is
    # looked up directly by code, never created.
    (WHT_SALE_RECEIVABLE_CODE, 'ADVANCE INCOME TAX AGAINST LOCAL SUPPLIES', 'asset_current'),
]

# Existing Sales Tax accounts this module's GST taxes post to - must
# already exist on this company's real CoA (same codes as the
# full-import variant uses); looked up directly here instead of from an
# account_by_code dict built during a CoA import, since this variant
# doesn't do one.
_GST_OUTPUT_ACCOUNT_CODE = '3.11.05.0002'  # SALES TAX PAYABLE - OUTPUT
_GST_INPUT_ACCOUNT_CODE = '3.11.05.0001'   # SALES TAX REFUNDABLE - INPUT


class ResCompany(models.Model):
    _inherit = 'res.company'

    @api.model
    def _combine001_run_import(self):
        """Despite the name (kept identical to the full-import variant
        so the rest of the codebase - and the non-noupdate <function>
        tag that calls this on every install/upgrade, see
        data/combine001_import_run.xml - needs zero changes), this
        variant does NOT import any Chart of Accounts / opening balance
        / Customers / Vendors / product catalog data. It only ensures
        the handful of forward-looking accounts and company-level
        feature toggles this module's own behavioural customizations
        depend on - see the module-level docstring above for why."""
        company = self.env.company
        _logger.info("Combine001 (live): applying customizations for company %s", company.name)

        structural_by_code = self._combine001_ensure_structural_accounts(company)
        self._combine001_ensure_gst_taxes(company, structural_by_code)
        self._combine001_rename_delivery_picking_types(company)
        self._combine001_ensure_uom_group()
        self._combine001_ensure_po_approval(company)

        _logger.info("Combine001 (live): customizations applied.")

    def _combine001_ensure_po_approval(self, company):
        """BRD for Purchase Module Changes sec. 4/6: 'Only approved RFQs
        can be confirmed' / 'Unauthorized users should not be able to
        approve RFQs'. Odoo already ships a native mechanism for exactly
        this - company.po_double_validation ('two_step' routes
        confirmation through a 'to approve' state gated to
        purchase.group_purchase_manager) - forced on unconditionally
        here (amount threshold 0, so it applies to every RFQ regardless
        of value) rather than building a second, redundant approval
        state machine on top of purchase.order."""
        if company.po_double_validation != 'two_step' or company.po_double_validation_amount != 0:
            company.write({'po_double_validation': 'two_step', 'po_double_validation_amount': 0})
            _logger.info("Combine001: PO double-validation (approval) enabled for every RFQ regardless of amount.")

    def _combine001_ensure_uom_group(self):
        """Change Request Document for Sales Module (2026-09-28) sec. 2.1:
        UoM must be visible on every sales document line. Odoo hides the
        UoM field/column behind the 'Units of Measure & Packagings'
        feature toggle unless `uom.group_uom` is granted - granting it
        directly on the Internal User group is exactly what that toggle
        does under the hood."""
        group_user = self.env.ref('base.group_user')
        group_uom = self.env.ref('uom.group_uom')
        if group_uom not in group_user.implied_ids:
            group_user.write({'implied_ids': [(4, group_uom.id)]})
            _logger.info("Combine001: 'Units of Measure' feature enabled for all Internal Users.")

    def _combine001_rename_delivery_picking_types(self, company):
        """BRD sec. 7.1: 'Delivery Note' functionality is reused as-is,
        only the business-facing name changes to 'Delivery Challan' -
        each warehouse's own outgoing stock.picking.type record is real
        per-company data, not a fixed view/action, so it's renamed here.
        Idempotent: only touches records still on the stock default
        name, never overwrites a name a user has since customised."""
        picking_types = self.env['stock.picking.type'].search([
            ('company_id', '=', company.id), ('code', '=', 'outgoing'),
            ('name', 'in', ('Delivery Orders', 'Delivery')),
        ])
        if picking_types:
            picking_types.write({'name': 'Delivery Challans'})
            _logger.info("Combine001: %s outgoing picking type(s) renamed to 'Delivery Challans'.", len(picking_types))

    # -- new structural accounts (GST Saving, Withholding) ----------------

    def _combine001_ensure_structural_accounts(self, company):
        Group = self.env['account.group']
        existing_groups = {g.code_prefix_start: g for g in Group.search([('company_id', '=', company.root_id.id)])}
        for code, name in _STRUCTURAL_GROUPS:
            if code not in existing_groups:
                Group.create({
                    'name': name,
                    'code_prefix_start': code,
                    'code_prefix_end': code,
                    'company_id': company.root_id.id,
                })

        Account = self.env['account.account']
        codes = [c for c, _, _ in _STRUCTURAL_ACCOUNTS]
        existing_accounts = {a.code: a for a in Account.with_context(active_test=False).search([
            ('company_ids', 'in', company.id), ('code', 'in', codes),
        ])}
        account_by_code = {}
        for code, name, account_type in _STRUCTURAL_ACCOUNTS:
            vals = {
                'code': code, 'name': name, 'account_type': account_type,
                'active': True, 'company_ids': [(6, 0, [company.id])],
            }
            found = existing_accounts.get(code)
            if found:
                found.write(vals)
                account_by_code[code] = found.id
            else:
                account_by_code[code] = Account.create(vals).id
        return account_by_code

    # -- GST taxes ----------------------------------------------------------

    def _combine001_ensure_gst_taxes(self, company, structural_by_code):
        """The 4 GST taxes this module manages: Sale/Purchase x 18%/22%.
        18% is the default for both directions. Unlike the full-import
        variant, the output/input tax accounts are looked up directly by
        code here (must already exist on this company's real CoA) rather
        than from an account_by_code dict built during a CoA import."""
        if not company.country_id:
            pk = self.env.ref('base.pk', raise_if_not_found=False)
            if pk:
                company.country_id = pk.id

        Account = self.env['account.account']
        output_account = Account.search([
            ('company_ids', 'in', company.id), ('code', '=', _GST_OUTPUT_ACCOUNT_CODE),
        ], limit=1)
        input_account = Account.search([
            ('company_ids', 'in', company.id), ('code', '=', _GST_INPUT_ACCOUNT_CODE),
        ], limit=1)
        if not output_account or not input_account:
            _logger.warning(
                "Combine001: GST output/input account (%s / %s) not found on this company's Chart "
                "of Accounts - GST taxes not created. Set these up (or adjust the codes in "
                "models/res_company.py) and upgrade the module again.",
                _GST_OUTPUT_ACCOUNT_CODE, _GST_INPUT_ACCOUNT_CODE,
            )
            return {}
        output_account_id = output_account.id
        input_account_id = input_account.id

        TaxGroup = self.env['account.tax.group']
        tax_group = TaxGroup.search([('company_id', '=', company.id), ('name', '=', 'GST')], limit=1)
        if not tax_group:
            tax_group = TaxGroup.create({'name': 'GST', 'company_id': company.id})

        Tax = self.env['account.tax']
        tax_by_use_rate = {}
        for use, rate, account_id in (
            ('sale', 18, output_account_id),
            ('sale', 22, output_account_id),
            ('purchase', 18, input_account_id),
            ('purchase', 22, input_account_id),
        ):
            tax = Tax.search([
                ('company_id', '=', company.id),
                ('type_tax_use', '=', use),
                ('amount', '=', rate),
                ('x_combine001_gst', '=', True),
            ], limit=1)
            if not tax:
                direction_label = 'Sale' if use == 'sale' else 'Purchase'
                vals = {
                    'name': f"GST {rate}% ({direction_label})",
                    'type_tax_use': use,
                    'amount_type': 'percent',
                    'amount': rate,
                    'company_id': company.id,
                    'x_combine001_gst': True,
                    'tax_group_id': tax_group.id,
                    'invoice_repartition_line_ids': [
                        (0, 0, {'document_type': 'invoice', 'repartition_type': 'base'}),
                        (0, 0, {'document_type': 'invoice', 'repartition_type': 'tax', 'account_id': account_id}),
                    ],
                    'refund_repartition_line_ids': [
                        (0, 0, {'document_type': 'refund', 'repartition_type': 'base'}),
                        (0, 0, {'document_type': 'refund', 'repartition_type': 'tax', 'account_id': account_id}),
                    ],
                }
                tax = Tax.create(vals)
            tax_by_use_rate[(use, rate)] = tax

        company.account_sale_tax_id = tax_by_use_rate[('sale', 18)]
        company.account_purchase_tax_id = tax_by_use_rate[('purchase', 18)]
        return tax_by_use_rate
