{
    'name': 'Combine - Job Work Conversion',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Send material to a vendor for conversion, track standard vs actual yield, '
               'charge excess wastage back to the vendor and carry the full cost into the item',
    'description': """
Combine - Job Work Conversion
=============================
Material is sent to a vendor (processor) to be converted - doubling,
dyeing, weaving, ... - and comes back as a different item.

- Process Categories group similar processes; Processes carry the
  standard yield %, wastage tolerance, the charges per unit of measure
  (per kg sent, per kg received, or fixed), how excess wastage is
  recovered from the vendor, and an optional waste product.
- A Conversion Order records what was sent (weight, size, packaging,
  bags, cost), sends it to the "Job Work at Vendors" location, records
  each receipt (and any waste returned) and, on Close, works out the
  actual yield and wastage, the recovery from the vendor for wastage
  beyond the allowance, and the full cost:
      input cost + charges - recovery - waste value
  which becomes the received item's cost per unit. Draft vendor bill
  (charges) and draft debit note (recovery) are created for review.
- "Next Process" chains a further conversion: its input is this
  order's output at the cost accumulated so far, so every stage bears
  all the costs before it.

Standalone: depends only on Odoo's own Inventory valuation and
Accounting - not on combine001 or any other customization.
""",
    'author': 'Sibyl Technologies',
    'license': 'LGPL-3',
    'depends': ['stock_account'],
    'data': [
        'security/ir.model.access.csv',
        'data/conversion_data.xml',
        'wizard/conversion_receive_views.xml',
        'views/conversion_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
