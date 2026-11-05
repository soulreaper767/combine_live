{
    'name': 'Combine - Stores',
    'version': '19.0.1.2.0',
    'category': 'Inventory/Inventory',
    'summary': 'Demand Note -> Purchase Orders per supplier -> Gate Pass Inward -> Inspection -> GRN; Gate Pass Outward',
    'description': """
Combine - Stores
================
Purchasing and gate control for the stores:

1. Demand Note - a store user lists the items needed (quantities only)
   and submits it.
2. Purchase users see submitted demand notes and "Create Purchase
   Orders" from one or several of them: quantities and rates adjusted,
   a vendor per line, one purchase order per supplier. Each demand
   line shows ordered / received / pending.
3. Gate Pass Inward (IGP) - every arriving consignment, any category:
   party, purchase order, party invoice / DC reference, vehicle,
   driver, quantity per party document and counted at the gate,
   packages, gross / tare / net weight.
4. Inspection - accepted and rejected quantity per item with reason;
   rejected goods are either to be replaced (purchase order stays open)
   or cancelled from the purchase order.
5. Goods Receipt Note (GRN) - the store user receives only the accepted
   quantity into stock through the purchase order's own receipt, so the
   purchase order's received quantity (and what can be billed) follows
   the accepted quantity.
6. Gate Pass Outward (OGP) - sales deliveries (party, invoice reference,
   quantities, weights), rejected goods going back to the vendor, and
   any other outward movement.

7. Issue to Production - Material Issue Note from the store to a
   production department (each department has its own consumption
   location): quantities, and the value the stock leaves at (average /
   FIFO cost). Departments under Stores > Configuration.
8. Stores Registers (Stores > Reporting): IGP, Inspection, GRN, OGP,
   Delivery Challan and Material Issue registers - document by
   document with its items and totals; filters for period, parties,
   party types, items, item categories, status, departments.

Every document prints in the same layout as the Custom Reports, and so
does combine001's own Gate Pass ("Gate Pass (house style)").
Installing it changes no existing data.
""",
    'author': 'Sibyl Technologies',
    'license': 'LGPL-3',
    'depends': ['purchase_stock', 'sale_stock', 'partner_ledger_qty', 'combine001'],
    'data': [
        'security/stores_security.xml',
        'security/ir.model.access.csv',
        'data/stores_sequences.xml',
        'wizard/demand_po_wizard_views.xml',
        'views/stores_views.xml',
        'report/stores_reports.xml',
        'views/issue_register_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
