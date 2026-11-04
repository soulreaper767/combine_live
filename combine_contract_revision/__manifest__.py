{
    'name': 'Combine - Contract Revision',
    'version': '19.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'Reopen a confirmed contract for changes, reversing its deliveries and invoices first',
    'description': """
Combine - Contract Revision
===========================
A confirmed contract that has already been delivered and invoiced cannot
normally be changed. "Revise Contract" (Sales Managers) reverses every
impact and puts the contract back to draft so it can be corrected and
confirmed again:

1. Invoices of the contract are reset to draft and cancelled - they keep
   their numbers, so no series gets a gap. Commission lines raised by
   those invoices (not yet paid) are removed and GST Saving entries
   cancelled, when those features are installed.
2. Every validated delivery is returned in full (Odoo's own return,
   counting anything already returned), so stock comes back.
3. Open deliveries are cancelled and the contract goes back to draft.

Refused while any invoice of the contract has a payment registered -
reverse or unreconcile the payment first. Everything done is written to
the contract's chatter. Standalone: depends only on Odoo's Sales,
Inventory and Accounting; installing it changes no data.
""",
    'author': 'Sibyl Technologies',
    'license': 'LGPL-3',
    'depends': ['sale_stock', 'account'],
    'data': ['views/sale_order_views.xml'],
    'installable': True,
    'application': False,
    'auto_install': False,
}
