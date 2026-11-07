{
    'name': 'Custom Reports (Partner Ledger)',
    'version': '19.0.7.11.0',
    'category': 'Accounting/Accounting',
    'summary': "House for this company's custom reports - starts with the Partner Ledger "
               "Qty column and the itemized Partner Statement PDF",
    'description': """
Custom Reports
==============
General-purpose home for this company's custom reporting work, grown
beyond the original single Qty-column feature - deliberately its own
standalone module, independent of every other customization on this
instance (combine001 included). Installing, upgrading or uninstalling
this module touches nothing else, and nothing else touches this.
Depends only on Odoo's own `account_reports`.

Display name only, technical name unchanged on purpose: this module's
folder/technical identity is still `partner_ledger_qty` (only the
`name` field shown in Apps changed to "Custom Reports") - a real
rename was tried and reverted after it left the old technical module
stuck mid-upgrade with no code to upgrade to, blocking the whole
registry from loading. Updating code under the same technical name
instead lets Odoo finish whatever it already has in progress.

Partner Ledger - Qty column
----------------------------
Adds a "Qty" column to the native Partner Ledger report (Accounting ->
Reporting -> Partner Ledger), positioned between "Matching" and "Debit".
Shows the invoiced quantity on Sales Invoice lines only - blank on vendor
bills, payments, credit notes and miscellaneous journal entries.

Uses `account_reports`' own documented extension hook
(`_get_additional_column_aml_values` on the Partner Ledger report's
handler model) to add one extra SQL-selected column to its existing
query, plus one new `account.report.column` record pointing at the
existing `account_reports.partner_ledger_report` via its own `report_id`
field. No core report file, no other column, and no other report on this
instance is modified in any way. Safe to uninstall at any time - the
native Partner Ledger report reverts to exactly its out-of-the-box
state.

Partner Ledger Print (itemized Partner Statement PDF)
------------------------------------------------------
A dedicated menu item - Accounting > Reporting > Partner Ledger Print,
right below the native "Partner Ledger" entry - opens a plain dialog:
pick a Partner, pick a date range, click Generate Report (PDF) or
Generate Excel (.xlsx, same columns/totals/number formats). Produces an
itemized Statement of Account for that partner: one row per
invoice/bill LINE ITEM (not per invoice), with the full pricing/tax
breakdown - Voucher Date, Voucher No., Remarks, Item Name, Invoice Age,
Gross Rate, Quantity, Discount, Net Rate, Ex. Amount, GST Rate, GST
Amount, Incl Amount - then a thick vertical divider, then Debit,
Credit, running Balance (advancing per line item). Payments/misc
entries still appear as their own row with the item/pricing columns
blank.

An earlier version of this put a "Statement PDF" button directly on
the native Partner Ledger report's own toolbar, requiring that report
to be filtered to one partner first via its own Partner filter - that
filter turned out hard to find/use in practice, so this plain, simple
dialog replaces it entirely.

This is its own report with its own query and its own QWeb template -
NOT a re-skin of the native Partner Ledger (see report/
partner_statement_report.py for the full reasoning: that report's
PDF export is rendered through account_reports' own generic template,
shared by every report on that engine, with no per-report override of
columns or header layout available).

Trial Balance with Party
------------------------
Accounting > Reporting > Trial Balance with Party (next to the native
Trial Balance): pick a date range, Generate Report (PDF) or Generate
Excel. Same figures as the native Trial Balance - Opening / Period
Debit & Credit / Closing per account, income/expense accounts reset at
the fiscal-year start with earlier years on one "Undistributed
Profits/Losses" line - plus each customer's / vendor's own balance
listed, indented, under its receivable / payable control account.
Party lines are a breakdown of the control account above them and are
not added again into the totals.

Party Outstanding Report
------------------------
Accounting > Reporting > Party Outstanding Report: Customers or
Vendors, a date range, optionally one or more partner categories
(tags). One line per party: Sr., Party Name, Last Delivery (receipt,
for vendors) Date, Last Invoice Date, Opening, Gross Sales/Purchases,
Net (after credit notes), Receipts/Payments, Others, Closing - all read
from the party's own receivable/payable journal items, so
Closing = Opening + Net - Receipts/Payments + Others always holds.
Vendor amounts are shown as positive amounts owed. Delivery dates are
read only when the Inventory app is installed (no new dependency).

Daily Documents Register (Accounting / Sales / Purchase > Reporting):
every document of the selected days - contracts, invoices, credit
notes, deliveries, purchase orders, bills, receipts, stores documents
(demand notes, IGP, inspections, GRN, OGP, material issues, conversion
orders, where installed) and bank / cash / journal vouchers - one block
per document type with count and totals; drafts included or not.

Bank & Cash Voucher Register: bank receipts, bank payments, cash
receipts, cash payments, journal vouchers - one line per voucher per
book (receipts / payments columns) or every account line per voucher.

Party control accounts
----------------------
Four accounts for all parties: 3.09.15 Trade Debtors - Control,
2.07.15 Trade Creditors - Control, 2.07.16 Advances from Customers,
3.09.16 Advances to Suppliers. Every customer / vendor points to the two
controls (new parties by default). Old invoices / bills keep their old
account and are paid on it as before; every other receivable / payable
account is archived as soon as nothing is open on it (at upgrade, then
daily). Posted entries are never edited.
Advances: tick "Advance" on a payment to post it to the advance account;
"Apply Advance" on the invoice / bill settles it from the party's open
advances (transfer entry, reconciled both sides).

Registers
---------
Sales > Reporting / Purchase > Reporting (and Accounting > Reporting):
Sales Register and Purchase Register - every invoice / bill line,
party-wise or item-wise (or a one-line-per-party/item summary), with
rate, discount %, gross, discount, net, sales tax and value incl. tax;
filters for parties, party types, items and item categories (raw
material, stores, ...). Contract / Sales Order Status and Purchase
Order Status - document by document: ordered, delivered (received),
balance, invoiced (billed), still to invoice, and the values. All in
the house style, PDF and Excel, through one shared register engine.

Party Types
-----------
Accounting > Configuration > Party Types: your own list (Local Customer,
Export Customer, Raw Material Supplier, ...). Each party carries one
("Party Type", next to Tags). Partner Ledger Print, Trial Balance with
Party and Party Outstanding Report each take a "Party Types" selection:
empty = all parties, or only the chosen types.

Voucher and Sales Tax Invoice prints
------------------------------------
Print menu of journal entries / invoices / bills: "Voucher" - one
format for every accounting voucher, titled from the entry itself
(Journal, Bank/Cash Payment or Receipt, Sales, Purchase, Credit/Debit
Note Voucher): account lines with debit/credit, amount in words,
signature boxes. Payments: "Payment Voucher" (same format, from the
payment's own entry). Customer invoices / credit notes: "Sales Tax
Invoice (FBR)" carrying every particular of section 23(1) of the Sales
Tax Act 1990 - supplier and buyer name, address, NTN and STRN; serial
number; date of issue; description, HS code and quantity; value
excluding tax; sales tax rate and amount; value including tax.
Purchase orders: "RFQ / Purchase Order" in the same layout as the
contract. Deliveries, receipts and transfers: "Delivery Challan /
Transfer" (quantities and weights, no prices).
Contracts and sales orders: "Contract / Sales Order" in the same layout
(titled Contract until confirmed, Sales Order after) - seller and buyer
with NTN / STRN, HS code, quantities, rates and values with and without
sales tax, amount in words, terms and signatures.
Odoo's own "Invoices" print used to fail with "Only invoices could be
printed." on any selection containing a plain journal entry; such
selections now print as vouchers instead.

Corporate letterhead-free design (no competing automatic header):
built on web.html_container directly rather than web.external_layout,
so there is exactly one company/partner header block, not two
overlapping ones. Thousands separators and parenthesised negatives on
every amount, centered column headings, a single green accent colour,
thin horizontal rules only (no vertical borders except the one
deliberate divider) - a dense, SAP-style line-item layout rather than
a decorative one.
""",
    'author': 'Sibyl Technologies',
    'license': 'LGPL-3',
    'depends': ['account_reports', 'sale', 'purchase_stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/party_type_views.xml',
        'views/document_date_views.xml',
        'data/qty_column.xml',
        'wizard/partner_statement_wizard_views.xml',
        'report/report_base_templates.xml',
        'report/partner_statement_report.xml',
        'wizard/trial_balance_party_wizard_views.xml',
        'report/trial_balance_party_report.xml',
        'wizard/party_outstanding_wizard_views.xml',
        'report/party_outstanding_report.xml',
        'report/voucher_report.xml',
        'report/sale_order_report.xml',
        'report/register_report.xml',
        'wizard/trade_registers_views.xml',
        'wizard/daily_registers_views.xml',
        'views/party_accounts_views.xml',
        'views/purchase_bill_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
