{
    'name': 'Combine Tax - Tax Rate Columns',
    'version': '19.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Sales tax rate column (sortable, filterable, groupable) on sales orders, purchase orders, invoices and bills',
    'description': """
Combine Tax - Tax Rate Columns
==============================
Adds "Tax Rate %" (the highest sales tax rate on the document's lines)
and "Tax Rates" (every rate on it, e.g. "18%, 22%") to the Sales
Orders / Quotations, Purchase Orders / RFQs, Customer Invoices and
Vendor Bills lists - sort by the column, search it, or Group By "Tax
Rate". Standalone; depends only on Odoo's Sales, Purchase and
Accounting apps.
""",
    'author': 'Sibyl Technologies',
    'license': 'LGPL-3',
    'depends': ['sale', 'purchase', 'account'],
    'data': ['views/tax_rate_views.xml'],
    'pre_init_hook': 'pre_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
