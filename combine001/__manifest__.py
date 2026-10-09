{
    'name': 'Combine001',
    'version': '19.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'Combine Spinning — Sales, Quantity Control, Tax, Commission & Accounting enhancements + this company\'s real CoA/Debtors/Vendors/Yarn data',
    'description': """
Combine001 — Odoo ERP Enhancements for Combine Spinning
=========================================================
LIVE VARIANT (repo: combine_live): every behavioural customization
below, plus this company's own real Chart of Accounts (structure
only, no opening trial balance), Debtors/Creditors control accounts,
2,476 customers, 346 vendors and the Yarn product catalog - sourced
directly from the live server's own exports, not the full-import
variant's (repo: combine001) bundled demo-company CSVs. Opening
balances are still NOT imported. See models/res_company.py's module
docstring and README.md ("Chart of Accounts" / "Live Debtors, Vendors
& Finished Goods" sections) for exactly what each import does and
does not touch.

Implements the Business Requirements Document "Odoo ERP Enhancements v1.0"
(Sibyl Technologies, 2026-09-16):

* Sales Order price-change approval workflow with audit trail
* Quotation -> Sales Order quantity control, plus item-wise and
  customer-wise quantity limits
* Cumulative delivery and invoice quantity validation against the Sales
  Order
* Additional charges (freight, transportation, handling, service) on the
  Sales Order
* Commission Agent assignment, automatic commission calculation on
  invoice posting, and commission reporting
* Separate Tax Ledger view and a controlled manual Tax Ledger Adjustment
  approval flow with full audit trail
* Role-based security groups (Tax Officer, Auditor) aligned to the BRD's
  RACI / access matrix, plus one demo user per BRD role (Section 3.1)
  already assigned to the correct groups
* On install AND on every upgrade: imports this company's real Chart
  of Accounts (structure only), Debtors/Creditors control accounts,
  Yarn products, customers and vendors from the live server's own
  exports; ensures the handful of forward-looking accounts (GST
  Saving, Withholding) this module's own features need; does NOT
  import opening trial balance or bank journals (see the full-import
  `combine001` repo for the variant that bundles its own self-contained
  demo data instead, meant for throwaway/demo/dev databases only)
* Relabels the core Sales app's document terminology (menus, buttons,
  filters, PDF report/print) to match the textile-trade terms Combine
  Spinning actually uses: Quotation -> Contract, confirmed Sales Order ->
  Delivery Order, Delivery Note -> Delivery Challan — cosmetic only, the
  underlying sale.order/stock.picking models and workflow are unchanged
* Configures GST 18%/22% Sale + Purchase taxes (18% default), posting to
  this company's existing GST output/input accounts (looked up by code -
  does NOT import a product catalog, unlike the full-import variant);
  and automatically records "GST Saved" (Dr Current Asset / Cr Equity,
  entirely outside the P&L) whenever an invoice or bill posts with no
  GST charged, computed from the rate on each product's master — see
  models/res_company.py and models/account_move.py / README
* Implements the "BRD for sales.docx" / Change Request Document for
  Sales Module workflow: Contract -> Delivery Order -> Delivery Challan
  -> Gate Pass -> Sales Invoice. Contract price is locked the moment the
  order is confirmed and can only change through a controlled Contract
  Amendment (draft -> submit -> Sales Manager approval -> apply, full
  chatter audit trail, always updates the existing line so reapplying
  never duplicates it); the Delivery Order is generated directly by
  Odoo's own native procurement on confirmation (no separate "Delivery
  Out" document/step); the existing Delivery Note/stock.picking
  functionality is reused as-is and relabeled "Delivery Challan" (the
  only document that actually deducts stock, on validation, exactly as
  before); a no-stock-impact Gate Pass is raised from a validated
  Delivery Challan; every document carries the Contract/registration-
  status reference back to its origin; Unit of Measure is enabled
  company-wide and shown on every one of these documents and their PDF
  reports
* Customer/Vendor "Tax Info" tab with separate Registered/Unregistered
  (or Filer/Non-Filer) status per tax regime - GST, Income Tax, PRA -
  that flows automatically onto every document above; PRA status is only
  shown on a document when a PRA-applicable product (flagged in that
  product's own Sales tab) is on one of its lines
* Commission Report payment tracking: Paid/Unpaid status, payment
  reference/date, Outstanding/Paid commission columns, and a bulk "Mark
  as Paid" action
* Withholding tax automation on Payments: an "Is Withholding Applicable"
  checkbox (defaulted automatically when registering payment against a
  GST-bearing bill, purchase side), a per-partner time-ranged
  Withholding Tax Rate table with exemption periods (a possibly-0%
  reduced rate for the exemption's duration, standard rate resumes
  after), correct net-of-withholding accounting entries via Odoo's own
  native payment-withholding mechanism, tagged to Chart of Accounts
  accounts (reusing an existing leaf account purchase-side, adding one
  new leaf sale-side — see models/account_payment.py / README), and a
  Withholding Tax Variance report comparing what a customer actually
  withheld against what the configured rate says they should have
* Implements the "BRD for Purchase Module Changes in Odoo": RFQ/PO price
  and quantity lock on confirmation (same amendment-only escape hatch as
  the sales side), RFQ approval via Odoo's own native PO double-
  validation (forced on for every RFQ regardless of amount) reinforced
  with an explicit Purchase Manager check, a matching custom approval
  workflow (Draft -> Submitted -> Approved -> Done/Posted, with Reject)
  for Purchase Receipt and Vendor Bill (which have no native equivalent),
  a PO Amendment process mirroring Contract Amendments, and a Purchase
  Commission Agent process (Draft -> Confirmed -> Payable -> Paid,
  configurable commission basis: PO/received/invoice/paid value) linked
  through to the vendor payment

Several points are explicitly left open in the BRD for client sign-off
(Section 12, "Open Items for Functional Design"). This module ships a
documented default for each so the app is usable end-to-end; see the
README for the assumptions made and how to change them:

1. Quantity hierarchy precedence -> all applicable limits enforced
   independently (most restrictive wins).
2. Price-override approval -> flat rule, any change from the quoted
   price routes to a Sales Manager.
3. Invoicing policy -> order-based (invoice qty validated against the
   Sales Order quantity).
4. Commission base -> configurable per Commission Agent / Sales Order,
   defaults to Sales Value.
5. Customer accounting dimension -> native partner_id on journal items
   (Odoo's built-in Partner Ledger), no separate GL account per customer.
6. Tax Ledger adjustment approval -> single level (Finance Manager).
""",
    'author': 'Sibyl Technologies',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'sale_management', 'sale_stock', 'account', 'uom', 'purchase', 'purchase_stock'],
    'data': [
        'security/combine001_security.xml',
        'security/ir.model.access.csv',
        'data/combine001_charge_data.xml',
        'data/ir_sequence_data.xml',
        'data/combine001_users_data.xml',
        'views/product_template_views.xml',
        'views/res_partner_views.xml',
        'views/customer_item_limit_views.xml',
        'views/charge_type_views.xml',
        'views/commission_agent_views.xml',
        'views/commission_line_views.xml',
        'wizard/add_charge_wizard_views.xml',
        'wizard/commission_payment_wizard_views.xml',
        'views/sale_amendment_views.xml',
        'views/purchase_amendment_views.xml',
        'views/purchase_commission_line_views.xml',
        'views/gate_pass_views.xml',
        'views/sale_order_views.xml',
        'views/sale_quotation_to_contract_views.xml',
        'views/sale_order_to_delivery_order_views.xml',
        'views/stock_picking_delivery_challan_views.xml',
        'views/account_move_uom_views.xml',
        'views/purchase_order_views.xml',
        'views/stock_picking_purchase_views.xml',
        'views/account_move_purchase_views.xml',
        'views/tax_adjustment_views.xml',
        'views/tax_ledger_views.xml',
        'views/gst_saving_views.xml',
        'views/withholding_rate_views.xml',
        'views/account_payment_views.xml',
        'views/audit_views.xml',
        'views/combine001_menus.xml',
        'data/combine001_import_run.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
