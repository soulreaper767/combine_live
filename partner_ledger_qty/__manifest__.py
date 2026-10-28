{
    'name': 'Partner Ledger - Qty Column',
    'version': '19.0.2.0.0',
    'category': 'Accounting/Accounting',
    'summary': "Adds an invoiced-quantity column to the native Partner Ledger report, "
               "plus a separate corporate-formatted Partner Statement PDF",
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
button on the Contact form opens a small wizard (date range), which
prints a corporate-formatted Statement of Account for that partner -
Journal, Invoice Date, Inv Qty, Debit, Credit, Balance, Remarks, with
an Opening Balance row and a running Balance per line. The company's
own details appear on the left of the header, the partner's on the
right (letterhead-style), and the currency is named once near the
title ("Amounts in <currency>") rather than repeated on every amount.

This is its own report with its own query and its own QWeb template -
NOT a re-skin of the native Partner Ledger. That report's PDF/XLSX
export is rendered through account_reports' own generic template,
shared by every report built on that engine (Trial Balance, General
Ledger, ...) - there is no way to give one specific report a different
column set or header layout within that shared template. Building a
separate report was the only way to get this exact layout without
touching (or risking) anything else built on that engine. See
report/partner_statement_report.py for the full reasoning.

The only pre-existing view touched anywhere in this module is one
additive button on the Contact form (res.partner) - no existing field,
button or behaviour on that view is changed.
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
