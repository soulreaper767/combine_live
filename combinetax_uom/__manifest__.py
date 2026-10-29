{
    'name': 'Combine - Sync Units',
    'version': '19.0.1.1.0',
    'category': 'Inventory/Inventory',
    'summary': 'Creates the units, stores/packing categories and price precision this setup needs',
    'description': """
Combine - Sync Units
====================
Standalone setup module - depends only on Odoo's own `stock_account`, not on
combine001, Master-Child Sync or any other customization. Re-checked
on every upgrade, create-if-missing only: an existing unit, category,
account or setting is never changed or duplicated.

- Units of measure (matched by exact name - Master-Child Sync needs
  them on both sides): Bag, Box, Set, Packet, Bottle, Pair, Gallon,
  Roll, Coil. Created standalone (no conversion); Units, kg, L, m and
  ft already ship with Odoo.
- Product categories "Stores & Spares" and "Packing Material": Average
  costing, automated (perpetual) valuation, stock valuation account
  3.07.01.0001 / 3.07.01.0002 (created as current assets only if that
  code does not exist yet).
- "Product Price" decimal accuracy raised to 4 (never lowered).
""",
    'author': 'Sibyl Technologies',
    'license': 'LGPL-3',
    'depends': ['stock_account'],
    'data': ['data/ensure_units.xml'],
    'installable': True,
    'application': False,
    'auto_install': False,
}
