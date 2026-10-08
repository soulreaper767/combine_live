import csv
import logging
import os

from odoo import api, models

from .combine001_constants import (
    GST_SAVING_ASSET_CODE, GST_SAVING_EQUITY_CODE, WHT_SALE_RECEIVABLE_CODE,
)

_logger = logging.getLogger(__name__)

# --- live Debtors / Finished Goods (Yarn) data --------------------------
# Unlike the rest of this module, these two imports DO ship real data
# (data/import/customers.csv, products.csv) - sourced from the live
# server's own "CUSTOMERS LIST.xlsx" / "PRODUCTS LIST WITH INVENTORY
# BALANCE.xls" (30-9 sheet), not the combine001 repo's CoA/opening-
# balance bundle. See README.md for exactly what these two files are and
# how they were derived (item names cleaned/standardised: whitespace
# collapsed, consistent colour spelling, "<count/quality/packing> -
# <colour>"; quantities only kept as a reference column, never applied
# as opening stock - same discipline as the full-import variant's
# product import).
_IMPORT_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'import')


def _read_csv(filename):
    path = os.path.join(_IMPORT_DIR, filename)
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


# The 14 Debtors control accounts (one per sub-ledger, matching this
# company's own real numbering 3.09.01-3.09.14). 6 of these already
# exist as real postable accounts on the live CoA (3.09.01/.02/.04/.11/
# .13/.14) and are simply found-and-updated here; the other 8 have no
# bare group-level account in the real CoA (only individual named leaf
# accounts under some of them) so this is the first time they're
# created - at the group-level code itself, the same pattern the real
# CoA already uses for the other 6, not a new convention.
_DEBTOR_CONTROL_ACCOUNTS_FILE = 'debtor_groups.csv'

# Finished Goods (Yarn) - this company's own real account codes, the
# same ones the full-import variant's product_categories.csv also
# points every yarn category at (see that repo's
# data/import/product_categories.csv). Found-and-reused where they
# already exist on this database, created at these exact codes where
# they don't yet - same find-or-create discipline as the structural
# GST Saving/Withholding accounts above, see
# _combine001_ensure_yarn_category.
_YARN_INCOME_ACCOUNT_CODE = '4.01.01.0001'   # LOCAL SALES - YARN
_YARN_EXPENSE_ACCOUNT_CODE = '5.18.02.0002'
_YARN_STOCK_ACCOUNT_CODE = '3.08.01.0001'

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
        variant does NOT import any opening balance / Customers /
        Vendors / product catalog data the way the full-import repo
        does. It DOES import the Chart of Accounts structure (account
        codes/names/types only, no opening balances - see
        _combine001_import_coa) from this company's own real CoA
        export, plus the handful of forward-looking accounts and
        company-level feature toggles this module's own behavioural
        customizations depend on - see the module-level docstring above
        for the rest."""
        company = self.env.company
        _logger.info("Combine001 (live): applying customizations for company %s", company.name)

        self._combine001_cancel_generic_coa_auto_install()
        self._combine001_import_coa(company)
        self._combine001_ensure_default_accounts(company)
        structural_by_code = self._combine001_ensure_structural_accounts(company)
        self._combine001_ensure_gst_taxes(company, structural_by_code)
        self._combine001_rename_delivery_picking_types(company)
        self._combine001_ensure_uom_group()
        self._combine001_ensure_po_approval(company)
        self._combine001_import_live_customers(company)
        self._combine001_import_live_products(company)

        _logger.info("Combine001 (live): customizations applied.")

    def _combine001_cancel_generic_coa_auto_install(self):
        """Installing the 'account' module (a combine001 dependency)
        unconditionally queues a one-shot callback on the registry that
        auto-installs Odoo's fallback 'Generic Chart of Accounts'
        template (with its own journals/accounts, overwriting whatever
        this company already has) the moment the *whole* module graph
        finishes loading - regardless of what this method, or anything
        else, does afterwards. That callback is queued while
        chart_template is still unset, so setting chart_template later
        does not stop it; the only way to stop it is to remove the
        queued callback itself. Unlike the full-import combine001 repo
        (which pairs this with its own CoA import), combine_live does
        NOT import a CoA - this guard exists purely so the accounts THIS
        module creates (Debtors control accounts, Yarn Income/COGS/
        Stock) on a company that doesn't yet have a chart template
        aren't silently wiped out again right after being created.
        Ported back in after the live server showed exactly that
        symptom: customers imported, but their receivable-account link
        gone - the generic fallback had fired after
        _combine001_ensure_debtor_control_accounts already created the
        14 control accounts, on a company with no chart_template set."""
        registry = self.env.registry
        if hasattr(registry, '_auto_install_template'):
            del registry._auto_install_template

    def _combine001_clear_account_references(self, company, accounts):
        """Before deleting any account.account record, every place that
        might point at it needs clearing first or the delete is blocked
        (or, worse for an ir.default, blocks a LATER unrelated delete
        with a confusing "used as the default value of ..." error - see
        the ir.default gotcha noted elsewhere in this codebase). Shared
        by _combine001_import_coa (deleting anything not in the real
        CoA export) - used to only cover Odoo's generic fallback chart,
        now covers any account being retired for any reason."""
        if not accounts:
            return
        company_fields = [
            'transfer_account_id', 'income_currency_exchange_account_id',
            'expense_currency_exchange_account_id', 'account_journal_suspense_account_id',
            'account_journal_payment_debit_account_id', 'account_journal_payment_credit_account_id',
            'account_journal_early_pay_discount_gain_account_id',
            'account_journal_early_pay_discount_loss_account_id',
            'default_cash_difference_income_account_id', 'default_cash_difference_expense_account_id',
        ]
        for f in company_fields:
            if f in company._fields and company[f] in accounts:
                company[f] = False

        journal_fields = [
            'default_account_id', 'suspense_account_id', 'profit_account_id', 'loss_account_id',
            'payment_debit_account_id', 'payment_credit_account_id',
        ]
        for journal in self.env['account.journal'].search([('company_id', '=', company.id)]):
            for f in journal_fields:
                if f in journal._fields and journal[f] in accounts:
                    journal[f] = False

        IrDefault = self.env['ir.default']
        for d in IrDefault.search([('field_id.relation', '=', 'account.account')]):
            try:
                if d.json_value and int(d.json_value) in accounts.ids:
                    d.unlink()
            except (ValueError, TypeError):
                continue

    # -- real Chart of Accounts (structure only, no opening balances) ---

    def _combine001_import_coa(self, company):
        """This company's own real Chart of Accounts - 700 accounts:
        1,017 exported directly from the live server's Accounting >
        Chart of Accounts list, minus 2 stray generic-chart leftovers
        that export accidentally picked up ('400000 Product Sales',
        '251000 Tax Received' - recognisable the same way as elsewhere
        in this file: every one of this company's own real codes is
        dotted, e.g. '3.09.01', the generic chart's never are), plus
        the 8 Debtors sub-ledger control codes -
        3.09.03/.05/.06/.07/.08/.09/.10/.12 - that genuinely don't exist
        even in that real export, minus 323 "party-wise"
        Receivable/Payable leaf accounts (one GL account per individual
        customer/vendor, e.g. '3.09.01.0106 HAJI ASHRAF ALI ANSARI' /
        '2.07.06.0011 OLYMPIA TEXTILE INTERNATIONAL - COMMISSION AGENT')
        deliberately filtered out - this company does not want a
        separate GL account per party, only the control-level accounts
        (3-segment codes, e.g. '3.09.01', vs. the party-wise 4-segment
        ones) stay, matching the "one control account per sub-ledger,
        not one per customer" design already used throughout this repo
        (see _combine001_import_live_customers and the "Customer
        accounting dimension" assumption in the README) - individual
        parties are tracked via Odoo's native Partner Ledger instead.
        data/import/coa.csv: code, name, account_type, reconcile - the
        exact "Code"/"Account Name"/"Type"/"Allow Reconciliation"
        columns that view exports, "Type" mapped from its display
        label, e.g. "Receivable", to the internal selection value, e.g.
        asset_receivable. Structure only - no opening balances are
        posted (no opening_debit/opening_credit column in the source at
        all), same "stage 1 is master data only" discipline as
        everywhere else in this repo; a full opening trial balance, if
        wanted later, is a separate, deliberate piece of work.

        Full replace, every upgrade: any account on this company whose
        code is NOT in this file is removed first (unlinked if nothing
        references it yet, archived instead if something already does -
        same safety net as the generic-chart removal this replaced),
        clearing any company/journal/ir.default reference to it first
        so the delete isn't blocked. What IS in the file always has its
        name/type/reconcile overwritten to match - this file is the
        single source of truth, including correcting any placeholder
        name this module itself may have guessed earlier (e.g. 3.09.01
        was first created here as "DEBTORS - LOCAL"; the real export's
        name is "TRADE DEBTORS - LOCAL SALES (GENERAL)")."""
        rows = _read_csv('coa.csv')
        target_codes = {r['code'] for r in rows}
        Account = self.env['account.account'].with_context(active_test=False)

        stale = Account.search([('company_ids', 'in', company.id), ('code', 'not in', list(target_codes))])
        removed = kept = 0
        if stale:
            self._combine001_clear_account_references(company, stale)
            for account in stale:
                try:
                    with self.env.cr.savepoint():
                        account.unlink()
                    removed += 1
                except Exception:
                    account.write({'active': False})
                    kept += 1

        existing = {a.code: a for a in Account.search([
            ('company_ids', 'in', company.id), ('code', 'in', list(target_codes)),
        ])}
        to_create = []
        updated = 0
        for row in rows:
            vals = {
                'code': row['code'],
                'name': row['name'],
                'account_type': row['account_type'],
                'reconcile': row['reconcile'] == 'True',
            }
            found = existing.get(row['code'])
            if found:
                found.write(vals)
                updated += 1
            else:
                vals['company_ids'] = [(6, 0, [company.id])]
                to_create.append(vals)
        if to_create:
            Account.create(to_create)
        _logger.info(
            "Combine001 (live): Chart of Accounts replaced - %s account(s) removed, %s archived "
            "(still referenced), %s created, %s updated.", removed, kept, len(to_create), updated,
        )

    def _combine001_ensure_default_accounts(self, company):
        """Replacing the whole Chart of Accounts every upgrade (above)
        blanks out every company/journal default-account field that
        pointed at whatever got removed - this re-sets the ones with an
        unambiguous, defensible real-account answer. Deliberately does
        NOT guess the rest (which of 30 real bank accounts backs which
        Odoo bank journal, which of 11 split-by-fibre raw-material
        accounts a purchase journal should default to) - those need a
        human decision, so a clear warning is logged instead, listing
        exactly which journals still need one set manually."""
        Account = self.env['account.account']
        cash_in_hand = Account.search([('code', '=', '3.14.01.0001')], limit=1)  # CASH IN HAND - HEAD OFFICE
        if cash_in_hand:
            company.transfer_account_id = cash_in_hand.id

        receivable_default = Account.search([('code', '=', '3.09.01')], limit=1)  # TRADE DEBTORS - LOCAL SALES (GENERAL)
        payable_default = Account.search([('code', '=', '2.07.09')], limit=1)  # CREDITORS - OTHERS
        IrDefault = self.env['ir.default']
        if receivable_default:
            IrDefault.set('res.partner', 'property_account_receivable_id', receivable_default.id, company_id=company.id)
        if payable_default:
            IrDefault.set('res.partner', 'property_account_payable_id', payable_default.id, company_id=company.id)

        yarn_income = Account.search([('code', '=', _YARN_INCOME_ACCOUNT_CODE)], limit=1)
        sale_journals = self.env['account.journal'].search([('company_id', '=', company.id), ('type', '=', 'sale')])
        if yarn_income:
            for journal in sale_journals:
                if not journal.default_account_id:
                    journal.default_account_id = yarn_income.id

        unset = self.env['account.journal'].search([
            ('company_id', '=', company.id), ('type', 'in', ('bank', 'cash', 'purchase')),
            ('default_account_id', '=', False),
        ])
        if unset:
            _logger.warning(
                "Combine001 (live): %s journal(s) still have no default account set - no safe, "
                "unambiguous real-account match exists, these need a manual choice: %s",
                len(unset), unset.mapped('name'),
            )

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

    # -- live Debtors (customers) --------------------------------------

    def _combine001_ensure_debtor_control_accounts(self, company):
        rows = _read_csv(_DEBTOR_CONTROL_ACCOUNTS_FILE)
        Account = self.env['account.account']
        codes = [r['code'] for r in rows]
        existing = {a.code: a for a in Account.with_context(active_test=False).search([
            ('company_ids', 'in', company.id), ('code', 'in', codes),
        ])}
        account_by_code = {}
        for row in rows:
            code = row['code']
            found = existing.get(code)
            if found:
                account_by_code[code] = found.id
            else:
                vals = {
                    'code': code, 'name': row['name'], 'account_type': 'asset_receivable',
                    'reconcile': True, 'company_ids': [(6, 0, [company.id])],
                }
                account_by_code[code] = Account.create(vals).id
        return account_by_code

    def _combine001_import_live_customers(self, company):
        """2,492 customers from the live server's own "CUSTOMERS LIST.xlsx"
        (Debtors sheet), collapsed into the 14 real sub-ledger control
        accounts (see _combine001_ensure_debtor_control_accounts) rather
        than one GL account per customer - same discipline as the
        full-import variant's customers.csv (see that repo's README,
        "Customer accounting dimension" open item)."""
        account_by_code = self._combine001_ensure_debtor_control_accounts(company)
        rows = _read_csv('customers.csv')
        Partner = self.env['res.partner']
        existing = {p.name: p for p in Partner.search([('customer_rank', '>', 0)])}

        to_create = []
        for row in rows:
            account_id = account_by_code.get(row['receivable_account_code'])
            vals = {
                'name': row['name'],
                'company_type': 'company',
                'customer_rank': 1,
            }
            if account_id:
                vals['property_account_receivable_id'] = account_id
            found = existing.get(row['name'])
            if found:
                found.write(vals)
            else:
                to_create.append(vals)
        if to_create:
            Partner.create(to_create)
        _logger.info("Combine001 (live): %s customers imported/updated.", len(rows))

    # -- live Finished Goods (Yarn) products -----------------------------

    def _combine001_ensure_yarn_category(self, company):
        """These 3 codes are Combine Spinning's own real account numbers
        (same ones the full-import variant's product_categories.csv
        points every yarn category at) - not invented here. Find-or-
        create, same idiom as _combine001_ensure_structural_accounts /
        _combine001_ensure_debtor_control_accounts: on a live database
        that already has them, they're simply found and reused; on one
        that doesn't yet (this company's numbering, just not fully set
        up on this particular database), they're created at that exact
        code. No opening balance is posted either way - stage 1 is
        master data (accounts + product catalog) only."""
        Account = self.env['account.account']
        wanted = [
            (_YARN_INCOME_ACCOUNT_CODE, 'LOCAL SALES - YARN', 'income'),
            (_YARN_EXPENSE_ACCOUNT_CODE, 'COST OF YARN SOLD', 'expense'),
            (_YARN_STOCK_ACCOUNT_CODE, 'STOCK - YARN', 'asset_current'),
        ]
        codes = [c for c, _, _ in wanted]
        existing = {a.code: a for a in Account.with_context(active_test=False).search([
            ('company_ids', 'in', company.id), ('code', 'in', codes),
        ])}
        accounts = {}
        for code, name, account_type in wanted:
            found = existing.get(code)
            if found:
                accounts[code] = found
            else:
                accounts[code] = Account.create({
                    'code': code, 'name': name, 'account_type': account_type,
                    'company_ids': [(6, 0, [company.id])],
                })

        Category = self.env['product.category']
        parent = Category.search([('name', '=', 'Finished Goods'), ('parent_id', '=', False)], limit=1)
        if not parent:
            parent = Category.create({'name': 'Finished Goods'})
        categ = Category.search([('name', '=', 'Yarn'), ('parent_id', '=', parent.id)], limit=1)
        vals = {
            'name': 'Yarn',
            'parent_id': parent.id,
            'property_valuation': 'periodic',
            'property_account_income_categ_id': accounts[_YARN_INCOME_ACCOUNT_CODE].id,
            'property_account_expense_categ_id': accounts[_YARN_EXPENSE_ACCOUNT_CODE].id,
            'property_stock_valuation_account_id': accounts[_YARN_STOCK_ACCOUNT_CODE].id,
        }
        if categ:
            categ.write(vals)
        else:
            categ = Category.create(vals)
        return categ

    def _combine001_import_live_products(self, company):
        """149 Yarn products from the live server's own "Products List
        FINAL.xlsx" - supersedes the earlier 126-item list sourced from
        "PRODUCTS LIST WITH INVENTORY BALANCE.xls" (30-9 sheet), which
        this method now also retires (deletes/archives). Item names
        standardised: whitespace collapsed, spelling typos fixed
        (TWWERA->TWEERA, AUTAIRO/AUTOAIR->AUTOAIRO), unmatched stray
        parentheses dropped. The source file has no quantity data at
        all (unlike the previous list's reference-only bag counts) -
        this is master data only, same "no opening stock without a
        trustworthy count" discipline as everywhere else in this repo."""
        categ = self._combine001_ensure_yarn_category(company)
        if not categ:
            return
        rows = _read_csv('products.csv')
        names = [r['name'] for r in rows]
        Product = self.env['product.template']

        stale = Product.search([('categ_id', '=', categ.id), ('name', 'not in', names)])
        if stale:
            try:
                stale.unlink()
            except Exception:
                stale.write({'active': False})
            _logger.info("Combine001 (live): %s stale Yarn product(s) retired.", len(stale))

        unit = self.env.ref('uom.product_uom_unit')
        existing = {p.name: p for p in Product.search([('name', 'in', names)])}

        to_create = []
        for name in names:
            vals = {
                'name': name,
                'categ_id': categ.id,
                'type': 'consu',
                'is_storable': True,
                'uom_id': unit.id,
                'sale_ok': True,
                'purchase_ok': True,
            }
            found = existing.get(name)
            if found:
                found.write(vals)
            else:
                to_create.append(vals)
        if to_create:
            Product.create(to_create)
        _logger.info("Combine001 (live): %s Yarn products imported/updated.", len(rows))
