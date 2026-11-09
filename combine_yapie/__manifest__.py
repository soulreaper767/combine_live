{
    'name': 'Combine - Yapie approvals',
    'version': '19.0.1.0.0',
    'category': 'Productivity',
    'summary': "Yapie approval cards follow combine001's own approval workflows: same documents, same approvers, same buttons",
    'description': """
Combine - Yapie approvals
=========================
Declares combine001's approval workflows to Yapie for Odoo, so the Yapie
approval rules are generated from them ("Sync with Odoo workflows") and can
never disagree with Odoo:

- Purchase Receipt (submitted)            - any Purchase Manager
- Vendor Bill / Debit Note (submitted)    - any Accounting Manager
- Contract price change (pending)         - any Sales Manager
- Contract Amendment (pending approval)   - any Sales Manager
- Purchase Order Amendment (pending)      - any Purchase Manager
- Tax Adjustment (pending approval)       - any Accounting Manager

(Purchase Order two-step approval is built into Yapie for Odoo itself.)

Approvers are read live from those Odoo groups; only members who linked
Yapie get the card; Approve / Reject run the document's own combine001
buttons as that approver; a rejection reason goes to the document's
rejection reason. Cards for documents decided inside Odoo are withdrawn.
""",
    'author': 'Sibyl Technologies',
    'license': 'LGPL-3',
    'depends': ['yapie', 'combine001', 'purchase_stock', 'account', 'sale'],
    'data': ['data/combine_yapie_data.xml'],
    'installable': True,
    'application': False,
    'auto_install': False,
}
