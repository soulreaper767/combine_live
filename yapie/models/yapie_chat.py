from odoo import _, fields, models
from odoo.exceptions import UserError


class YapieChat(models.Model):
    """A Yapie group the bot may post into. Before every post, the bot checks that every member of the group is a
    linked, authorised Odoo user (and, for reports and documents, allowed to see that content). If anyone else is
    in the group, nothing is posted."""
    _name = "yapie.chat"
    _description = "Yapie group"
    _order = "name"

    name = fields.Char(required=True)
    chat_id = fields.Integer("Yapie group ID", required=True,
                             help="Add the bot to the group in Yapie, then send it any message in the group: its ID is shown "
                                  "in Yapie › Activity, or ask Yapie support.")
    active = fields.Boolean(default=True)
    member_note = fields.Char("Last check", readonly=True)
    member_ok = fields.Boolean("All members authorised", readonly=True)

    _chat_unique = models.Constraint("UNIQUE(chat_id)", "This Yapie group is already registered.")

    def _member_users(self):
        """(users, strangers): the linked Odoo users in the group, and the names of anyone who isn't one."""
        self.ensure_one()
        users = self.env["res.users"].sudo().browse()
        strangers = []
        for m in self.env["yapie.api"].sudo().chat_members(self.chat_id):
            if m.get("is_bot"):
                continue
            u = self.env["res.users"]._yapie_by_uid(m.get("id"))
            if u and u._yapie_authorized():
                users |= u
            else:
                strangers.append(m.get("display_name") or m.get("username") or "?")
        return users, strangers

    def safe_for(self, allowed=None):
        """True if posting here only reaches authorised people (and, if `allowed` is a predicate on res.users,
        only people it accepts). Records the result on the group."""
        self.ensure_one()
        try:
            users, strangers = self._member_users()
        except UserError as e:
            self.sudo().write({"member_ok": False, "member_note": str(e)[:200]})
            return False
        if allowed:
            strangers += [u.name for u in users if not allowed(u)]
        ok = not strangers
        self.sudo().write({"member_ok": ok, "member_note": _("%s member(s), all authorised") % len(users) if ok
                           else _("Not authorised: %s") % ", ".join(strangers[:8])})
        return ok

    def action_check_members(self):
        for c in self:
            c.safe_for()
        return True
