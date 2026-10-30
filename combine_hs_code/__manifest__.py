{
    'name': 'Combine - HS Code',
    'version': '19.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'HS Code on products, on the Sales and Purchase analysis reports and the Sales Tax Invoice print',
    'description': """
Combine - HS Code
=================
Adds an "HS Code" (Pakistan Customs Tariff / PCT heading) to products,
next to Category. It is available as a group-by and filter in Sales >
Reporting and Purchase > Reporting, and prints as its own column on
the "Sales Tax Invoice (FBR)" (Custom Reports module).

Standalone: depends only on Odoo's own Sales and Purchase apps - not on
combine001 or any other customization, and changes no existing record.
The field is named `hs_code`, the same name Odoo's own shipping module
uses, so the two never conflict.
""",
    'author': 'Sibyl Technologies',
    'license': 'LGPL-3',
    'depends': ['sale', 'purchase'],
    'data': ['views/hs_code_views.xml'],
    'installable': True,
    'application': False,
    'auto_install': False,
}
