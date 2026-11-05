{
    'name': 'Combine - Sync Extras',
    'version': '19.0.1.0.1',
    'category': 'Accounting',
    'summary': 'Master-side additions to Master-Child Sync: create missing taxes / journals / states in the Child, '
               'never clash on account codes, show the real reason when a sync fails',
    'description': """
Combine - Sync Extras
=====================
Install on the Master (combine) only - where Master-Child Sync is installed as
`odoo_master_child` (the combine_live submodule). Extends it without
changing it:

- Taxes, journals and states missing in the Child are created there
  automatically (same name / code / rate / accounts) instead of
  blocking the sync. Taxes are no longer silently dropped.
- Units, currencies and other reference records that exist in the
  Child but are archived are found and used, instead of being
  reported as missing.
- Accounts: when the Child already has the same account code for a
  different account, the Master's account is created in the Child
  under the next free code of the same series (e.g. 2.07.04.0345 ->
  2.07.04.0346) instead of failing or overwriting the Child's own
  account.
- Background (bulk) sync creates missing customers, vendors, products,
  categories and accounts on its own instead of leaving documents
  "pending".
- A failed sync records the actual error on the document instead of
  "Bulk sync failed - see server log".

Installing or upgrading it changes no existing data.
""",
    'author': 'Sibyl Technologies',
    'license': 'LGPL-3',
    'depends': ['odoo_master_child'],
    'data': [],
    'installable': True,
    'application': False,
    'auto_install': False,
}
