import logging
from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..tools import PERIODS, period_range

_logger = logging.getLogger(__name__)


class YapieReportSchedule(models.Model):
    """Send a report on a schedule — e.g. every Monday at 9:00, last week's sales to the sales managers."""
    _name = "yapie.report.schedule"
    _description = "Scheduled Yapie report"
    _order = "next_run, id"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    report_type_id = fields.Many2one("yapie.report.type", "Report", required=True, ondelete="cascade", domain=[("active", "=", True)])
    report_code = fields.Char(related="report_type_id.code")
    needs_partner = fields.Selection(related="report_type_id.needs_partner")
    partner_id = fields.Many2one("res.partner", "Customer / vendor")
    text_filter = fields.Char("Filter", help="Stock on hand: only products whose name contains this")
    period = fields.Selection(PERIODS, default="last_month", required=True)
    fmt = fields.Selection([("pdf", "PDF"), ("xlsx", "Excel")], "Format", default="pdf", required=True)
    frequency = fields.Selection([("daily", "Every day"), ("weekly", "Every week"), ("monthly", "Every month")], default="weekly", required=True)
    weekday = fields.Selection([(str(i), d) for i, d in enumerate(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])], default="0")
    month_day = fields.Integer("Day of month", default=1)
    hour = fields.Integer("At (hour, 0–23)", default=9)
    run_as_id = fields.Many2one("res.users", "Prepared as", required=True, default=lambda s: s.env.user, domain=[("share", "=", False)],
                                help="The report is prepared with this person's Odoo access rights and company.")
    recipient_ids = fields.Many2many("res.users", "yapie_schedule_user_rel", "schedule_id", "user_id", "Send to", domain=[("share", "=", False)])
    chat_ids = fields.Many2many("yapie.chat", string="Send to groups")
    next_run = fields.Datetime(readonly=True, copy=False)
    last_run = fields.Datetime(readonly=True, copy=False)
    last_note = fields.Char(readonly=True, copy=False)

    @api.constrains("month_day", "hour")
    def _check_numbers(self):
        for s in self:
            if not 1 <= s.month_day <= 28:
                raise ValidationError(_("Day of month: 1 to 28 (so it runs every month)."))
            if not 0 <= s.hour <= 23:
                raise ValidationError(_("Hour: 0 to 23."))

    @api.constrains("report_type_id", "run_as_id", "recipient_ids", "partner_id")
    def _check_recipients(self):
        for s in self:
            rt = s.report_type_id
            if not rt.allowed_for(s.run_as_id):
                raise ValidationError(_("%(u)s isn't allowed to get %(r)s (or hasn't linked Yapie).", u=s.run_as_id.name, r=rt.name))
            bad = s.recipient_ids.filtered(lambda u: not rt.allowed_for(u))
            if bad:
                raise ValidationError(_("Not allowed to get %(r)s, or not linked to Yapie: %(names)s", r=rt.name, names=", ".join(bad.mapped("name"))))
            if rt.needs_partner == "required" and not s.partner_id:
                raise ValidationError(_("%s needs a customer or vendor.") % rt.name)
            if not s.recipient_ids and not s.chat_ids:
                raise ValidationError(_("Choose who gets it."))

    # ---------- timing ----------
    def _tz(self):
        return pytz.timezone(self.run_as_id.tz or self.env.user.tz or "UTC")

    def _compute_next(self, after=None):
        self.ensure_one()
        tz = self._tz()
        now_local = (after or datetime.utcnow()).replace(tzinfo=pytz.utc).astimezone(tz).replace(tzinfo=None)
        d = now_local.date()
        for _i in range(400):
            ok = (self.frequency == "daily" or (self.frequency == "weekly" and d.weekday() == int(self.weekday or 0))
                  or (self.frequency == "monthly" and d.day == self.month_day))
            cand = datetime.combine(d, time(self.hour))
            if ok and cand > now_local:
                return tz.localize(cand).astimezone(pytz.utc).replace(tzinfo=None)
            d += timedelta(days=1)
        return False

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        for r in recs:
            r.next_run = r._compute_next()
        return recs

    def write(self, vals):
        res = super().write(vals)
        if {"frequency", "weekday", "month_day", "hour", "run_as_id"} & set(vals) and not self.env.context.get("yapie_no_reschedule"):
            for r in self:
                r.with_context(yapie_no_reschedule=True).next_run = r._compute_next()
        return res

    # ---------- running ----------
    @api.model
    def _cron_run(self):
        for s in self.search([("active", "=", True), ("next_run", "<=", fields.Datetime.now())], limit=50):
            s._run()
            s.with_context(yapie_no_reschedule=True).write({"next_run": s._compute_next(), "last_run": fields.Datetime.now()})
            self.env.cr.commit()

    def action_send_now(self):
        for s in self:
            s._run()
            s.with_context(yapie_no_reschedule=True).last_run = fields.Datetime.now()
        return {"type": "ir.actions.client", "tag": "display_notification",
                "params": {"title": _("Yapie"), "message": self[:1].last_note or "", "type": "info"}}

    def _run(self):
        """Prepare once (as `run_as`), send to every recipient still allowed, and to groups whose members are all allowed."""
        self.ensure_one()
        api_ = self.env["yapie.api"].sudo()
        rt = self.report_type_id
        Report = self.env["yapie.report"].sudo()
        user = self.run_as_id.sudo()
        try:
            env = Report.with_user(user).with_company(user.company_id).env
            today = fields.Date.context_today(env.user)
            f, t = period_range(self.period, today, Report.fy_start(env, today))
            params = {"partner_id": self.partner_id.id, "date_from": f, "date_to": t, "text": self.text_filter or ""}
            name, mime, content, caption = Report.generate(rt, user, params, self.fmt)
        except Exception as e:  # noqa: BLE001
            note = _("Could not prepare: %s") % str(e)[:200]
            self.sudo().last_note = note
            self.env["yapie.log"].add("schedule", "%s — %s" % (self.name, note), user=user, state="error", rule_ref="schedule:%s" % self.id)
            return False
        caption = "🗓️ %s\n%s" % (self.name, caption)
        sent, skipped = [], []
        for u in self.recipient_ids.sudo():
            if not rt.allowed_for(u):
                skipped.append(u.name)
                continue
            try:
                api_.send_file(api_.target_of(u), name, mime, content, caption)
                sent.append(u.name)
            except UserError as e:
                skipped.append("%s (%s)" % (u.name, e))
        for c in self.chat_ids:
            if c.safe_for(lambda u: rt.allowed_for(u)):
                try:
                    api_.send_file({"chat_id": c.chat_id}, name, mime, content, caption)
                    sent.append(c.name)
                except UserError as e:
                    skipped.append("%s (%s)" % (c.name, e))
            else:
                skipped.append(_("%(g)s (%(why)s)", g=c.name, why=c.member_note))
        note = _("Sent to %s") % (", ".join(sent) or _("nobody"))
        if skipped:
            note += _(" · not sent to %s") % "; ".join(skipped)
        self.sudo().last_note = note[:250]
        self.env["yapie.log"].add("schedule", "%s — %s" % (self.name, note), user=user, state="ok" if sent else "error", rule_ref="schedule:%s" % self.id)
        return bool(sent)
