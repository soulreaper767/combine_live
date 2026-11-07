import logging
import re
from datetime import datetime, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def ms_to_dt(ms):
    return datetime.utcfromtimestamp(int(ms) / 1000.0).replace(microsecond=0) if ms else False


def digits(s):
    d = re.sub(r"\D", "", s or "")
    return d[-10:] if len(d) >= 10 else ""


class YapieApi(models.AbstractModel):
    _inherit = "yapie.api"

    @api.model
    def _dispatch(self, event, data):
        if event == "attendance":
            return self.env["yapie.attendance.event"].sudo().receive(data)
        return super()._dispatch(event, data)


class HrAttendance(models.Model):
    _inherit = "hr.attendance"

    in_mode = fields.Selection(selection_add=[("yapie", "Yapie")], ondelete={"yapie": "set default"})
    out_mode = fields.Selection(selection_add=[("yapie", "Yapie")], ondelete={"yapie": "set default"})
    yapie_record_id = fields.Integer("Yapie attendance", index=True, copy=False, readonly=True)
    yapie_place = fields.Char("Checked in at", readonly=True)
    yapie_status = fields.Char("Yapie status", readonly=True, help="present / late, as Yapie saw it")


class YapieAttendanceOrg(models.Model):
    """A Yapie Work organisation that connected this Odoo. Nothing is recorded until it's enabled here."""
    _name = "yapie.attendance.org"
    _description = "Yapie organisation"
    _order = "name"

    name = fields.Char(required=True, readonly=True)
    org_id = fields.Integer("Yapie organisation", required=True, readonly=True)
    enabled = fields.Boolean("Record attendance", help="Create Odoo attendance from this organisation's check-ins")
    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, required=True)
    member_ids = fields.One2many("yapie.attendance.member", "org_ref", readonly=True)
    member_count = fields.Integer("Members", compute="_compute_counts")
    unmatched_count = fields.Integer("Not matched yet", compute="_compute_counts")
    pending_count = fields.Integer("Check-ins waiting", compute="_compute_counts")
    last_sync = fields.Datetime("Members synced", readonly=True)

    _org_unique = models.Constraint("UNIQUE(org_id)", "This organisation is already here.")

    def _compute_counts(self):
        for o in self:
            o.member_count = len(o.member_ids)
            o.unmatched_count = len(o.member_ids.filtered(lambda m: not m.employee_id and not m.ignore))
            o.pending_count = self.env["yapie.attendance.event"].search_count([("org_ref", "=", o.id), ("state", "=", "pending")])

    @api.model
    def _get(self, org_payload):
        org = self.search([("org_id", "=", int(org_payload.get("id") or 0))], limit=1)
        if not org:
            org = self.create({"org_id": int(org_payload["id"]), "name": org_payload.get("name") or "Yapie"})
            self.env["yapie.log"].add("attendance", _("Yapie organisation %s connected this Odoo — enable it in Yapie › Attendance to record attendance.") % org.name)
        elif org_payload.get("name") and org.name != org_payload["name"]:
            org.name = org_payload["name"]
        return org

    @api.model
    def action_fetch(self):
        """Organisations whose admin connected this bot in Yapie."""
        for o in self.env["yapie.api"].sudo().call("/orgs"):
            self._get(o)
        return {"type": "ir.actions.client", "tag": "soft_reload"}

    def action_sync_members(self):
        for org in self:
            members = self.env["yapie.api"].sudo().call("/orgs/%s/members" % org.org_id)
            for m in members:
                org.member_ids._upsert(org, m)
            org.last_sync = fields.Datetime.now()
            org.member_ids._auto_match()
        self.mapped("member_ids").filtered("employee_id")._apply_pending()
        return True

    def action_catch_up(self):
        return {"type": "ir.actions.act_window", "res_model": "yapie.attendance.catchup", "view_mode": "form", "target": "new",
                "name": _("Catch up from Yapie"), "context": {"default_org_ref": self.id}}

    def write(self, vals):
        res = super().write(vals)
        if vals.get("enabled"):
            # re-check everything waiting: matched members are recorded, the rest say why they still wait
            self.env["yapie.attendance.event"].sudo().search([("org_ref", "in", self.ids), ("state", "=", "pending")], order="id")._apply()
        return res


class YapieAttendanceMember(models.Model):
    """A member of a Yapie organisation, and the employee they are in Odoo."""
    _name = "yapie.attendance.member"
    _description = "Yapie organisation member"
    _order = "name"

    org_ref = fields.Many2one("yapie.attendance.org", "Organisation", required=True, ondelete="cascade", index=True)
    yapie_uid = fields.Integer("Yapie account", required=True, index=True, readonly=True)
    name = fields.Char(readonly=True)
    username = fields.Char(readonly=True)
    email = fields.Char(readonly=True)
    phone = fields.Char(readonly=True)
    department = fields.Char(readonly=True)
    title = fields.Char(readonly=True)
    employee_code = fields.Char(readonly=True)
    employee_id = fields.Many2one("hr.employee", "Employee", index=True)
    ignore = fields.Boolean("Don't record", help="e.g. an owner who isn't an employee")
    match_note = fields.Char(readonly=True)

    _member_unique = models.Constraint("UNIQUE(org_ref, yapie_uid)", "Already listed.")
    _employee_unique = models.Constraint("UNIQUE(org_ref, employee_id)", "That employee is already matched to another member.")

    def _upsert(self, org, m):
        vals = {"name": m.get("display_name") or m.get("username"), "username": m.get("username"), "email": m.get("email"),
                "phone": m.get("phone"), "department": m.get("department"), "title": m.get("title"), "employee_code": m.get("employee_code")}
        rec = self.search([("org_ref", "=", org.id), ("yapie_uid", "=", int(m["id"]))], limit=1)
        if rec:
            rec.write(vals)
        else:
            rec = self.create(dict(vals, org_ref=org.id, yapie_uid=int(m["id"])))
        return rec

    def _auto_match(self):
        """Match to an employee only when exactly one employee fits (badge ID, work email, or mobile)."""
        Emp = self.env["hr.employee"].sudo().with_context(active_test=True)
        for m in self.filtered(lambda x: not x.employee_id and not x.ignore):
            org_emps = Emp.search([("company_id", "in", (m.org_ref.company_id.id, False))])
            taken = self.search([("org_ref", "=", m.org_ref.id), ("employee_id", "!=", False)]).mapped("employee_id")
            cands, how = Emp.browse(), ""
            if m.employee_code:
                cands, how = org_emps.filtered(lambda e: e.barcode and e.barcode == m.employee_code), _("badge ID")
            if not cands and m.email:
                em = m.email.lower()
                cands, how = org_emps.filtered(lambda e: (e.work_email or "").lower() == em or (e.user_id.login or "").lower() == em), _("email")
            if not cands and digits(m.phone):
                ph = digits(m.phone)
                cands, how = org_emps.filtered(lambda e: ph in (digits(e.mobile_phone), digits(e.work_phone))), _("mobile")
            cands -= taken
            if len(cands) == 1:
                m.write({"employee_id": cands.id, "match_note": _("matched by %s") % how})
            else:
                m.match_note = _("several possible employees — choose one") if cands else _("no matching employee — choose one")

    def write(self, vals):
        if "employee_id" in vals and "match_note" not in vals:
            vals["match_note"] = _("chosen by hand") if vals["employee_id"] else False
        res = super().write(vals)
        if vals.get("employee_id"):
            self._apply_pending()
        return res

    def _apply_pending(self):
        Ev = self.env["yapie.attendance.event"].sudo()
        for m in self.filtered("employee_id"):
            Ev.search([("org_ref", "=", m.org_ref.id), ("yapie_uid", "=", m.yapie_uid), ("state", "=", "pending")], order="id")._apply()


class YapieAttendanceEvent(models.Model):
    """A check-in or check-out from Yapie, and what became of it in Odoo."""
    _name = "yapie.attendance.event"
    _description = "Yapie check-in / check-out"
    _order = "id desc"

    org_ref = fields.Many2one("yapie.attendance.org", "Organisation", required=True, ondelete="cascade", index=True)
    yapie_uid = fields.Integer(required=True, index=True)
    member_name = fields.Char()
    record_id = fields.Integer("Yapie record", index=True)
    action = fields.Selection([("in", "Check-in"), ("out", "Check-out")], required=True)
    check_in = fields.Datetime()
    check_out = fields.Datetime()
    place = fields.Char()
    method = fields.Char()
    status = fields.Char()
    state = fields.Selection([("pending", "Waiting"), ("done", "Recorded"), ("skipped", "Not recorded"), ("error", "Failed")],
                             default="pending", required=True, index=True)
    note = fields.Char()
    attendance_id = fields.Many2one("hr.attendance", ondelete="set null")
    employee_id = fields.Many2one(related="attendance_id.employee_id")

    @api.model
    def receive(self, data):
        org = self.env["yapie.attendance.org"].sudo()._get(data.get("org") or {})
        member = data.get("member") or {}
        m = self.env["yapie.attendance.member"].sudo()._upsert(org, member)
        m._auto_match()
        return self._from_record(org, member.get("id"), m.name, data.get("action"), data.get("record") or {})._apply()

    @api.model
    def _from_record(self, org, uid, name, action, r):
        return self.sudo().create({
            "org_ref": org.id, "yapie_uid": int(uid), "member_name": name, "record_id": r.get("id"), "action": "out" if action == "out" else "in",
            "check_in": ms_to_dt(r.get("check_in")), "check_out": ms_to_dt(r.get("check_out")), "place": r.get("place"),
            "method": r.get("method"), "status": r.get("status"),
        })

    def _apply(self):
        Att = self.env["hr.attendance"].sudo()
        for ev in self:
            org = ev.org_ref
            m = self.env["yapie.attendance.member"].sudo().search([("org_ref", "=", org.id), ("yapie_uid", "=", ev.yapie_uid)], limit=1)
            if m.ignore:
                ev.write({"state": "skipped", "note": _("member set to “don't record”")})
                continue
            if not org.enabled or not m.employee_id:
                ev.write({"state": "pending", "note": _("organisation not enabled yet") if not org.enabled else _("member not matched to an employee yet")})
                continue
            emp = m.employee_id
            try:
                with self.env.cr.savepoint():
                    att = Att.search([("yapie_record_id", "=", ev.record_id), ("employee_id", "=", emp.id)], limit=1) if ev.record_id else Att
                    if not att:
                        att = Att.search([("employee_id", "=", emp.id), ("check_in", "=", ev.check_in)], limit=1)
                    if not att:
                        att = Att.create({"employee_id": emp.id, "check_in": ev.check_in, "in_mode": "yapie", "yapie_record_id": ev.record_id,
                                          "yapie_place": ev.place, "yapie_status": ev.status,
                                          "in_location": ev.place or False})
                    if ev.check_out and not att.check_out:
                        att.write({"check_out": ev.check_out, "out_mode": "yapie"})
                    ev.write({"state": "done", "attendance_id": att.id, "note": False})
            except Exception as e:  # noqa: BLE001  e.g. it overlaps an attendance entered by hand
                ev.write({"state": "error", "note": str(e)[:200]})
        return True

    def action_retry(self):
        self.filtered(lambda e: e.state in ("pending", "error"))._apply()
        return True


class YapieAttendanceCatchup(models.TransientModel):
    _name = "yapie.attendance.catchup"
    _description = "Catch up attendance from Yapie"

    org_ref = fields.Many2one("yapie.attendance.org", required=True)
    date_from = fields.Date(required=True, default=lambda s: fields.Date.context_today(s) - timedelta(days=7))
    date_to = fields.Date(required=True, default=fields.Date.context_today)

    def action_run(self):
        self.ensure_one()
        if (self.date_to - self.date_from).days > 62 or self.date_to < self.date_from:
            raise UserError(_("Up to 62 days at a time."))
        org = self.org_ref
        org.action_sync_members()
        rows = self.env["yapie.api"].sudo().call("/orgs/%s/attendance" % org.org_id, query={"from": str(self.date_from), "to": str(self.date_to)})
        Ev = self.env["yapie.attendance.event"].sudo()
        members = {m.yapie_uid: m for m in org.member_ids}
        n = 0
        for r in rows:
            m = members.get(int(r.get("user_id") or 0))
            name = m.name if m else str(r.get("user_id"))
            done = Ev.search([("org_ref", "=", org.id), ("record_id", "=", r.get("id")), ("state", "=", "done")], limit=1)
            if done and (done.attendance_id.check_out or not r.get("check_out")):
                continue
            Ev._from_record(org, r.get("user_id"), name, "out" if r.get("check_out") else "in", r)._apply()
            n += 1
        self.env["yapie.log"].add("attendance", _("%(o)s: caught up %(n)s check-ins (%(f)s – %(t)s)", o=org.name, n=n, f=self.date_from, t=self.date_to))
        return {"type": "ir.actions.client", "tag": "display_notification",
                "params": {"title": _("Yapie"), "message": _("%s check-ins read from Yapie.") % n, "type": "success", "next": {"type": "ir.actions.act_window_close"}}}
