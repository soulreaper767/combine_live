{
    'name': 'Combine - Production Costing',
    'version': '19.0.1.1.0',
    'category': 'Inventory/Inventory',
    'summary': 'Spinning process routes, production batches, QC, waste, WIP, standard / actual / budget cost and variance; production and stock movement reports',
    'description': """
Combine - Production Costing
============================
Follows the material through the mill, department by department, and
costs it two ways - standard and actual - with the variance between them.

Process routes (Stores > Configuration > Process Routes)
-------------------------------------------------------
"Load Standard Spinning Flows" creates the departments and three routes:
- Carded: Blow Room > Carding > Breaker Drawing > Finisher Drawing >
  Speed Frame > Ring Spinning > Winding > Yarn Testing & QC > Packing
- Combed: ... Breaker Drawing > Sliver Lap Preparation > Comber
  Preparation > Combing > Finisher Drawing > Speed Frame > Ring ...
- Open-End: ... Finisher Drawing > Open-End / Rotor Spinning > Winding ...
Raw cotton receiving, bale inspection and the raw cotton warehouse are the
Stores flow (IGP > Inspection > GRN); the finished goods warehouse and
dispatch are Odoo's stock and the delivery challan. A batch on a route
sends its output to the next department by itself; Packing needs the
lot's approved final quality test (packing authorization).

Quality control: Quality Tests for raw cotton, sliver, roving, yarn and
the final approval, with the usual parameters filled in (staple, mic,
strength, trash; hank, U%, neps; count, CSP, IPI, hairiness ...).
Waste: Waste Collection Notes - department, waste item, classification
(reusable / recyclable / saleable / hard), bags, gross / tare / net -
received into the waste store at standard value, then reissued or sold.
Maintenance: use Odoo's Maintenance app (equipment, preventive
schedules, work orders, repair, release).

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
- Production Reports: Daily Production (finished goods first, then each
  department, then waste), Department Production (batch by batch), FG
  Production (item by day), WIP Summary, Process Cost Build-up (cost
  brought in and added in each process, per unit, against standard),
  Actual vs Budget (Production Budgets: quantity, cost / unit, waste %).
- Prints: Production Batch Report, WIP Count Sheet, Quality Test Report,
  Waste Collection Note.

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
        'views/production_flow_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
