{
    'name': 'Combine - Contract Quantity Amendment',
    'version': '19.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'Change the quantity of a confirmed or revised contract; delivery and invoice limits follow the new quantity',
    'description': """
Combine - Contract Quantity Amendment
=====================================
- The quantity of a confirmed contract line can be increased or decreased
  directly on the contract (no longer locked). The rate stays locked.
- A contract reopened by "Revise Contract" can take a quantity above the
  originally quoted one.
- The new quantity becomes the line's baseline, so the delivery and invoice
  limits are the new quantity, not the old one.
- A decrease below what is already delivered or invoiced (posted) is refused
  with a message saying what to correct first (return the delivery / issue a
  credit note).
- Every change is posted on the contract (old -> new, by whom) and shown to
  the user as a notification.

Adds behaviour only: installing it changes no existing record.
""",
    'author': 'Sibyl Technologies',
    'license': 'LGPL-3',
    'depends': ['combine001', 'sale_stock', 'combine_contract_revision'],
    'data': [],
    'installable': True,
    'application': False,
    'auto_install': False,
}
