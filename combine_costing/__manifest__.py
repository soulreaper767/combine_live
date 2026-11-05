{
    'name': 'Combine - Production Costing',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Department process flow, WIP, standard cost cards, actual cost and variance analysis; stock movement reports',
    'description': """
Combine - Production Costing
============================
Follows the material through the mill, department by department, and
costs it two ways - standard and actual - with the variance between them.

Flow
----
1. Store issues material to a department (Stores > Issue to Production).
2. Production Batch (Stores > Production): one run / lot in one
   department - inputs consumed from what the department holds, good
   output, waste, and where the output goes: the next department, the
   finished-goods store, or stays in the department.
3. Department Stock / WIP Count: physical count of what lies in a
   department; differences adjust the department's book stock.
4. Month-end Cost Close: each department's actual conversion cost (power,
   wages, overheads - from its cost centre (analytic account) in the books,
   plus any manual amount) spread over its batches by output.

Costing
-------
- Standard Cost Cards (Stores > Configuration): purchased items -
  standard price; produced items (lap, sliver, roving, yarn) - inputs per
  unit and standard conversion per unit; effective from a date.
- Actual: material at each department's average actual cost (store issue
  value, or the previous department's transfer value) + actual conversion.
- Output passes on at actual material + standard conversion; finished goods
  enter the store through a normal stock receipt at that value.
- Variances per batch: material price, material usage, conversion.

Reports (Stores > Reporting, PDF and Excel, house style)
-------------------------------------------------------
- Stock Movement Report: opening, received, from production, issued to
  production, delivered, other in / out, internal transfers, closing -
  quantity or value; item-wise, category-wise or lot-wise; any period.
- Department Stock & WIP: per department per item - issued from store,
  received from department, consumed, produced, transferred on, waste,
  closing (material + work in process).
- Cost & Variance Analysis: batch-wise, item-wise, department-wise or
  month-wise.
- Prints: Production Batch Report, WIP Count Sheet.

Odoo's own stock valuation method is not changed. New models only;
installing it changes no existing data.
""",
    'author': 'Sibyl Technologies',
    'license': 'LGPL-3',
    'depends': ['combine_stores', 'stock_account', 'analytic', 'partner_ledger_qty'],
    'data': [
        'security/ir.model.access.csv',
        'data/costing_sequences.xml',
        'views/costing_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
