from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


class YapieLinkWizard(models.TransientModel):
    """Link an Odoo user to their Yapie account. The bot sends a one-time code to that Yapie account; only the
    person who can read it there can finish linking. So nobody can attach someone else's Yapie to this company."""
    _name = "yapie.link.wizard"
    _description = "Link Yapie"

    user_id = fields.Many2one("res.users", required=True, default=lambda s: s.env.user, readonly=True)
    target = fields.Char("Your Yapie", help="Your @username, mobile number or email on Yapie")
    step = fields.Selection([("ask", "Ask"), ("code", "Code")], default="ask")
    request_id = fields.Char()
    yapie_uid = fields.Integer()
    code = fields.Char("Code")

    def _check(self):
        if self.user_id != self.env.user and not self.env.user.has_group("yapie.group_yapie_manager"):
            raise AccessError(_("You can only link your own Yapie account."))
        if not self.user_id.has_group("yapie.group_yapie_user"):
            raise UserError(_("%s isn't a Yapie user in Odoo yet (Settings › Users › Yapie).") % self.user_id.name)

    def _reopen(self):
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id, "view_mode": "form", "target": "new", "name": _("Link Yapie")}

    def action_send_code(self):
        self.ensure_one()
        self._check()
        target = (self.target or "").strip()
        if not target:
            raise UserError(_("Enter your Yapie @username, mobile number or email."))
        r = self.env["yapie.api"].sudo().call("/otp", {"to": target, "ttl_min": 10, "length": 6})
        uid = int(r.get("user_id") or 0)
        other = self.env["res.users"].sudo().with_context(active_test=False).search([("yapie_uid", "=", uid), ("id", "!=", self.user_id.id)], limit=1)
        if other:
            raise UserError(_("That Yapie account is already linked to another Odoo user."))
        self.write({"request_id": r.get("request_id"), "yapie_uid": uid, "step": "code", "target": target})
        return self._reopen()

    def action_verify(self):
        self.ensure_one()
        self._check()
        if not self.request_id:
            raise UserError(_("Send the code first."))
        r = self.env["yapie.api"].sudo().call("/otp/verify", {"request_id": self.request_id, "code": (self.code or "").strip()})
        if not r.get("valid"):
            raise UserError(_("That code isn't right (%s). Check the latest message from the bot in Yapie.") % (r.get("reason") or _("wrong code")))
        u = self.user_id.sudo()
        u.write({"yapie_uid": self.yapie_uid, "yapie_target": self.target, "yapie_linked_at": fields.Datetime.now(), "yapie_chat_id": 0})
        self.env["yapie.log"].add("link", _("%(u)s linked Yapie (%(t)s)", u=u.name, t=self.target), user=u)
        try:
            api_ = self.env["yapie.api"].sudo()
            api_.send_text(api_.target_of(u), _("✅ Linked to %(c)s as %(u)s. Send “menu” to see what I can do for you.", c=u.company_id.name, u=u.name))
        except UserError:
            pass
        return {"type": "ir.actions.client", "tag": "display_notification",
                "params": {"title": _("Yapie linked"), "message": _("%s's Yapie is linked.") % u.name, "type": "success",
                           "next": {"type": "ir.actions.act_window_close"}}}
