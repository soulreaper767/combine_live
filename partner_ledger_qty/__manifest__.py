{
    'name': 'Partner Ledger - Qty Column',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Accounting',
    'summary': "Adds an invoiced-quantity column to the native Partner Ledger report",
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
""",
    'author': 'Sibyl Technologies',
    'license': 'LGPL-3',
    'depends': ['account_reports'],
    'data': [
        'data/partner_ledger_qty_column.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
