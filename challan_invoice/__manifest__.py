{
    'name': 'Invoice per Delivery Challan',
    'version': '19.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'Create one customer invoice per validated Delivery Challan',
    'description': """
Invoice per Delivery Challan
============================
Adds an "Invoice this Challan" button on a validated outgoing Delivery
Challan that is linked to a Contract (Sales Order). It creates a draft
customer invoice for exactly that challan's delivered quantities, at
the Contract's own prices/taxes, linked to the Contract lines the same
way Odoo's own "Create Invoice" links them - so the Contract's invoiced
quantity, and any later native "Create Invoice", stay correct.

- One invoice per challan: a challan that already has a (non-cancelled)
  invoice opens that invoice instead of creating a second one.
- Never invoices more than is delivered and not yet invoiced on each
  Contract line.
- The invoice is left in draft; posting it goes through every existing
  check and posting step exactly as for any other invoice.

Deliberately its own standalone module, depending only on Odoo's own
`sale_stock`: it does not modify, upgrade or depend on any other
customization on this instance, changes no product, invoicing policy,
setting or existing record, and adds only one new field (the invoice's
link back to its challan). Uninstalling it removes that field and the
button and leaves every invoice in place.
""",
    'author': 'Sibyl Technologies',
    'license': 'LGPL-3',
    'depends': ['sale_stock'],
    'data': [
        'views/stock_picking_views.xml',
        'views/account_move_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
