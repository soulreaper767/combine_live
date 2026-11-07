from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

YAPIE_FIELDS = ["yapie_uid", "yapie_target", "yapie_username", "yapie_linked_at", "yapie_linked"]


class ResUsers(models.Model):
    _inherit = "res.users"

    # set only by the link wizard after the person proved they own the Yapie account (one-time code)
    yapie_uid = fields.Integer("Yapie account ID", copy=False, readonly=True, index=True)
    yapie_target = fields.Char("Linked with", copy=False, readonly=True, help="The @username, phone or email used to link.")
    yapie_username = fields.Char("Yapie username", copy=False, readonly=True)
    yapie_chat_id = fields.Integer("Chat with the bot", copy=False, readonly=True, groups="yapie.group_yapie_manager")
    yapie_linked_at = fields.Datetime("Linked on", copy=False, readonly=True)
    yapie_linked = fields.Boolean("Yapie linked", compute="_compute_yapie_linked", search="_search_yapie_linked")

    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + YAPIE_FIELDS

    @api.depends("yapie_uid")
    def _compute_yapie_linked(self):
        for u in self:
            u.yapie_linked = bool(u.yapie_uid)

    def _search_yapie_linked(self, operator, value):
        linked = (operator == "=") == bool(value)
        return [("yapie_uid", ">", 0)] if linked else ["|", ("yapie_uid", "=", 0), ("yapie_uid", "=", False)]

    @api.constrains("yapie_uid")
    def _check_yapie_unique(self):
        for u in self.filtered("yapie_uid"):
            if self.sudo().with_context(active_test=False).search_count([("yapie_uid", "=", u.yapie_uid), ("id", "!=", u.id)]):
                raise ValidationError(_("This Yapie account is already linked to another user."))

    def _yapie_authorized(self):
        """A person who may use the bot: an active internal user in 'Yapie: User', with a linked account."""
        self.ensure_one()
        u = self.sudo()
        return bool(u.active and u.yapie_uid and not u.share and u.has_group("yapie.group_yapie_user"))

    @api.model
    def _yapie_by_uid(self, uid):
        if not uid:
            return self.browse()
        return self.sudo().search([("yapie_uid", "=", int(uid))], limit=1)

    def _yapie_check_self_or_manager(self):
        if any(u != self.env.user for u in self) and not self.env.user.has_group("yapie.group_yapie_manager"):
            raise AccessError(_("You can only link or unlink your own Yapie account."))

    def action_yapie_link(self):
        self.ensure_one()
        self._yapie_check_self_or_manager()
        return {"type": "ir.actions.act_window", "res_model": "yapie.link.wizard", "view_mode": "form", "target": "new",
                "name": _("Link Yapie"), "context": {"default_user_id": self.id}}

    def action_yapie_unlink(self):
        self._yapie_check_self_or_manager()
        for u in self.sudo():
            if u.yapie_uid:
                self.env["yapie.log"].sudo().add("link", _("%s unlinked from Yapie") % u.name, user=u)
            u.write({"yapie_uid": 0, "yapie_target": False, "yapie_username": False, "yapie_chat_id": 0, "yapie_linked_at": False})
        return True

    def write(self, vals):
        # the link can't be set by hand (only the wizard proves ownership); unlinking goes through action_yapie_unlink
        if any(k in vals for k in ("yapie_uid", "yapie_target", "yapie_chat_id")) and not self.env.su:
            raise AccessError(_("Yapie accounts are linked with the one-time code (Link Yapie)."))
        return super().write(vals)
