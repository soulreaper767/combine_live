{
    'name': 'Custom Reports (Partner Ledger)',
    'version': '19.0.3.0.2',
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

Partner Statement PDF
---------------------
A "Statement PDF" button on the Partner Ledger report's own toolbar
(next to the native PDF/XLSX buttons) - filter the report to one
partner, click it, get an itemized Statement of Account for that
partner: one row per invoice/bill LINE ITEM (not per invoice), with the
full pricing/tax breakdown - Voucher Date, Voucher No., Remarks, Item
Name, Invoice Age, Gross Rate, Quantity, Discount, Net Rate, Ex. Amount,
GST Rate, GST Amount, Incl Amount - then a thick vertical divider, then
Debit, Credit, running Balance (advancing per line item). Payments/misc
entries still appear as their own row with the item/pricing columns
blank.

This is its own report with its own query and its own QWeb template -
NOT a re-skin of the native Partner Ledger (see report/
partner_statement_report.py for the full reasoning: that report's
PDF export is rendered through account_reports' own generic template,
shared by every report on that engine, with no per-report override of
columns or header layout available). Uses account_reports' real
per-report button mechanism (_init_options_buttons on account.report),
scoped to only the Partner Ledger report - every other report's button
bar is unaffected.

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
        'report/partner_statement_report.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
