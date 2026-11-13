{
    'name': 'Combine - Production Costing (FIFO)',
    'version': '19.0.1.0.0',
    'category': 'Manufacturing',
    'summary': 'Production entered at a unit cost, yarn on FIFO, delivery cost per production batch, production reports',
    'description': """
Production Costing (FIFO)
=========================

* Manufacturing Order gets a **Unit Cost**: the production is valued at
  quantity x unit cost, and that cost is saved on the item as its
  **Last Production Cost** (with date and order).
* Installing changes NO existing record: costing methods stay as they are.
  FIFO for Finished Goods / Yarn is a separate, deliberate step
  (product.category._combine_production_set_fifo, run only when approved).
* Every delivery of a FIFO item records which stock it came from - e.g.
  production 1 used up and part of production 2 - with quantity, rate and
  cost per batch (exactly the split Odoo used to cost the delivery).
* Reports (house-style PDF + Excel): Production Entries, Daily Production,
  Total Production, Delivery Cost.
""",
    'author': 'Combine',
    'license': 'LGPL-3',
    'depends': ['mrp_account', 'sale_stock', 'partner_ledger_qty'],
    'data': [
        'security/ir.model.access.csv',
        'views/mrp_production_views.xml',
        'views/product_views.xml',
        'views/fifo_allocation_views.xml',
        'wizard/production_report_views.xml',
        'wizard/delivery_cost_views.xml',
        'wizard/zero_cost_views.xml',
        'wizard/cost_revalue_views.xml',
        'views/cost_revaluation_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
}
