{
    'name': 'Partner Ledger - Qty Column',
    'version': '19.0.2.0.0',
    'category': 'Accounting/Accounting',
    'summary': "Adds an invoiced-quantity column to the native Partner Ledger report, "
               "plus a separate itemized Partner Statement PDF",
    'description': """
Partner Ledger - Qty Column
============================
Deliberately its own standalone module, independent of every other
customization on this instance (combine001 included) - installing,
upgrading or uninstalling this module touches nothing else, and nothing
else touches this. It depends only on Odoo's own `account_reports`.

What it does
------------
Adds a "Qty" column to the native Partner Ledger report (Accounting ->
Reporting -> Partner Ledger), positioned between "Matching" and "Debit".
Shows the invoiced quantity on Sales Invoice lines only - blank on vendor
bills, payments, credit notes and miscellaneous journal entries, exactly
as requested.

How
---
Uses `account_reports`' own documented extension hook
(`_get_additional_column_aml_values` on the Partner Ledger report's
handler model) to add one extra SQL-selected column to its existing
query, plus one new `account.report.column` record pointing at the
existing `account_reports.partner_ledger_report` via its own `report_id`
field. No core report file, no other column, and no other report on this
instance is modified in any way.

PDF and Excel (XLSX) export are both already native to every report
built on this engine - nothing extra was needed for that; the Qty column
appears in both export formats automatically, with the same corporate
formatting (fonts, sizing, layout) as every other native accounting
report on this instance.

Safe to uninstall at any time - removes the one new column and the one
override; the native Partner Ledger report reverts to exactly its
out-of-the-box state.

Partner Statement PDF
---------------------
A second, separate deliverable in this same module: a "Print Statement"
button on the Contact form opens a small wizard (date range), printing
an itemized Statement of Account for that single partner - one row per
invoice/bill LINE ITEM (not per invoice), with the full pricing/tax
breakdown: Voucher Date, Voucher No., Remarks, Item Name, Invoice Age,
Gross Rate, Quantity, Discount, Net Rate, Ex. Amount, GST Rate, GST
Amount, Incl Amount, then a thick vertical divider, then Debit, Credit,
Balance (running, advancing per line item). Payments/misc entries still
appear as their own row with the item/pricing columns blank. Company
details on the left of the header, partner's on the right; currency
named once near the title.

This is its own report with its own query and its own QWeb template -
NOT a re-skin of the native Partner Ledger (see report/
partner_statement_report.py for the full reasoning: that report's
PDF/XLSX export is rendered through account_reports' own generic
template, shared by every report on that engine, with no per-report
override of columns or header layout available). The only pre-existing
view touched anywhere in this module is one additive button on the
Contact form - no existing field, button or behaviour on that view is
changed.
""",
    'author': 'Sibyl Technologies',
    'license': 'LGPL-3',
    'depends': ['account_reports'],
    'data': [
        'security/ir.model.access.csv',
        'data/partner_ledger_qty_column.xml',
        'wizard/partner_statement_wizard_views.xml',
        'report/partner_statement_report.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
