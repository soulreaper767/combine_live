{
    "name": "Yapie for Odoo",
    "summary": "Run Odoo from Yapie chat: approvals by reply, review alerts, on-demand and scheduled reports — "
               "only for linked, authorised people",
    "description": """
Yapie for Odoo
==============
Connects this Odoo database to a Yapie bot.

* **Linked accounts** — each Odoo user links their own Yapie account with a one-time code sent to it in Yapie.
  Nobody else (not even other Yapie users) gets anything from this company.
* **Reports in chat** — linked people message the bot ("ledger Acme 1/7/2026 30/9/2026", "receivables excel")
  and get the PDF or Excel back. Who may get which report is set per report type; the report runs with the
  person's own Odoo access rights.
* **Scheduled reports** — e.g. every Monday 9:00 the receivables aging to the finance team.
* **Approvals** — rules per document type and condition: who may ask, who approves. Approvers tap Approve /
  Reject or reply "approve" / "reject - reason"; Odoo applies it as that approver.
* **Review alerts** — "Invoice INV/2026/0042 is ready for your review" to the right people when a document
  meets a condition.
* **Groups** — reports or alerts go to a Yapie group only when every member is a linked, authorised user.
* Works with a public Odoo (webhook) or one without a public address (polling).
""",
    "version": "19.0.1.1.0",
    "category": "Productivity",
    "author": "Yapie",
    "website": "https://yapie.app/integrations",
    "license": "LGPL-3",
    "depends": ["base", "mail", "web", "base_automation"],
    "external_dependencies": {"python": ["xlsxwriter"]},
    "data": [
        "security/yapie_security.xml",
        "security/ir.model.access.csv",
        "data/yapie_data.xml",
        "report/yapie_report_templates.xml",
        "wizard/yapie_link_wizard_views.xml",
        "wizard/yapie_approval_wizard_views.xml",
        "views/yapie_report_views.xml",
        "views/yapie_approval_views.xml",
        "views/yapie_notify_views.xml",
        "views/yapie_misc_views.xml",
        "views/res_users_views.xml",
        "views/res_config_settings_views.xml",
        "views/yapie_menus.xml",
    ],
    "application": True,
    "installable": True,
}
