{
    'name': 'Custom Reports (Partner Ledger)',
    'version': '19.0.7.0.0',
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
    'depends': ['account_reports'],
    'data': [
        'security/ir.model.access.csv',
        'data/qty_column.xml',
        'wizard/partner_statement_wizard_views.xml',
        'report/report_base_templates.xml',
        'report/partner_statement_report.xml',
        'wizard/trial_balance_party_wizard_views.xml',
        'report/trial_balance_party_report.xml',
        'wizard/party_outstanding_wizard_views.xml',
        'report/party_outstanding_report.xml',
        'report/voucher_report.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
