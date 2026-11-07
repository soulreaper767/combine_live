{
    "name": "Yapie Attendance",
    "summary": "Check-ins and check-outs from Yapie Work become Odoo attendance — for matched employees only",
    "description": """
Yapie Attendance
================
When a Yapie Work organisation's owner/admin connects this Odoo's bot (Yapie › Work › Organisation › Connected
systems), every check-in and check-out there arrives here:

* Organisations must also be **enabled** here by an HR / Yapie administrator.
* Members are matched to employees (work email, mobile or badge ID) — automatically when there's exactly one match,
  or by hand. Unmatched members' check-ins wait until they are matched; nothing is created for strangers.
* Creates and closes hr.attendance records (mode “Yapie”, with place, location and late status), never twice for
  the same check-in.
* “Catch up” re-reads a date range from Yapie after downtime.
""",
    "version": "19.0.1.0.0",
    "category": "Human Resources/Attendances",
    "author": "Yapie",
    "website": "https://yapie.app/integrations",
    "license": "LGPL-3",
    "depends": ["yapie", "hr_attendance"],
    "data": [
        "security/ir.model.access.csv",
        "views/yapie_attendance_views.xml",
    ],
    "auto_install": True,
    "installable": True,
}
