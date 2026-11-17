{
    'name': 'Combine - Tax Registration Status by Date',
    'version': '19.0.1.0.0',
    'category': 'Accounting',
    'summary': 'GST / Income Tax / PRA status per party for date ranges (like Withholding Tax Rates); '
               'each document takes the status in force on its own date',
    'description': '''
A party can become registered / unregistered (or filer / non-filer) at any time. Give each
party its status for a period (from / to) - Combine001 > Taxation > Registration Status by
Date, or the party's Tax Info tab.

* A contract, delivery challan, gate pass or invoice takes the status in force on its own
  date when it is created (a draft follows its date / party if they change; a contract takes
  the status of its confirmation date). With no period covering a date, the party's status on
  the Tax Info tab is used.
* The GST rate swap (18% registered / 22% unregistered) follows the document's status.
* A document that is confirmed / posted / done is never changed afterwards: a later change of
  the party's status or periods does not rewrite its status or its taxes (before this module a
  status change rewrote the taxes of confirmed contracts and posted invoices).
* Installing this module changes no existing record: documents keep the status they hold.
''',
    'author': 'Combine',
    'depends': ['combine001'],
    'data': [
        'security/ir.model.access.csv',
        'views/tax_status_period_views.xml',
        'views/res_partner_views.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}
