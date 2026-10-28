{
    'name': 'Custom Reports (deprecated - safe to uninstall)',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Accounting',
    'summary': "Leftover from an aborted module rename - has no features, no data, "
               "nothing to lose by uninstalling. See description.",
    'description': """
Deprecated - nothing to lose by uninstalling
=============================================
This module exists ONLY so Odoo has real code to finish whatever
install/upgrade it already had pending for the technical name
"custom_reports" - a rename to this name was tried, then reverted back
to "partner_ledger_qty" (which kept all the real functionality) once
the rename itself left this name stuck mid-install with no code at all
to install, which appeared to block the whole registry from loading.

This stub has no models, no views, no data, nothing - it exists purely
to let that stuck state resolve into something Odoo can then cleanly
uninstall. Once installed (or already in a settled state), go to Apps
and uninstall "Custom Reports (deprecated - safe to uninstall)" - there
is nothing in it to lose. The real reporting functionality lives in
the "Custom Reports (Partner Ledger)" module (technical name
partner_ledger_qty), untouched by any of this.
""",
    'author': 'Sibyl Technologies',
    'license': 'LGPL-3',
    'depends': ['account_reports'],
    'data': [],
    'installable': True,
    'application': False,
    'auto_install': False,
}
