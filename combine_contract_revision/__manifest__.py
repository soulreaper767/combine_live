{
    'name': 'Combine - Contract Revision',
    'version': '19.0.1.1.0',
    'category': 'Sales/Sales',
    'summary': 'Reopen a confirmed contract with its deliveries and invoices in draft - same documents, no stock or ledger effect',
    'description': """
Combine - Contract Revision
===========================
A confirmed contract that has already been delivered and invoiced cannot
normally be changed. "Revise Contract" (Sales Managers) puts the contract,
its deliveries and its invoices back to draft - the same documents with
the same numbers - with every stock and ledger effect removed:

1. Invoices go back to draft (number kept); commission lines raised by
   them (not yet paid) are removed and GST Saving entries cancelled,
   when those features are installed.
2. Validated deliveries go back to draft through Odoo's own correction
   of done quantities: stock returns to the warehouse, the delivery's
   value goes to zero, a stock journal entry (if any) is cancelled. No
   return document, nothing new in the ledger.
3. The contract goes back to draft for changes.
4. On confirming again, the reopened delivery takes the new quantities
   (new items join it, removed items drop out) and is ready to validate;
   the draft invoices take the new rates, discounts and taxes.

Refused while any invoice of the contract has a payment registered
(reverse or unreconcile it first), a credit note is posted, or goods
were returned against it. Everything done is written to
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
