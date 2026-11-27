from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

YAPIE_FIELDS = ["yapie_uid", "yapie_target", "yapie_username", "yapie_linked_at", "yapie_linked", "yapie_extra_link_ids"]


class ResUsers(models.Model):
    _inherit = "res.users"

    # set only by the link wizard after the person proved they own the Yapie account (one-time code)
    yapie_uid = fields.Integer("Yapie account ID", copy=False, readonly=True, index=True)
    yapie_target = fields.Char("Linked with", copy=False, readonly=True, help="The @username, phone or email used to link.")
    yapie_username = fields.Char("Yapie username", copy=False, readonly=True)
    yapie_chat_id = fields.Integer("Chat with the bot", copy=False, readonly=True, groups="yapie.group_yapie_manager")
    yapie_linked_at = fields.Datetime("Linked on", copy=False, readonly=True)
    yapie_linked = fields.Boolean("Yapie linked", compute="_compute_yapie_linked", search="_search_yapie_linked")
    # more people working through this one Odoo user, each with their own Yapie (see yapie.user.link)
    yapie_extra_link_ids = fields.One2many("yapie.user.link", "user_id", "Additional Yapie accounts")

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
            if self.env["yapie.user.link"].sudo().search_count([("yapie_uid", "=", u.yapie_uid)]):
                raise ValidationError(_("This Yapie account is already linked to another user."))

    def _yapie_authorized(self):
        """A person who may use the bot: an active internal user in 'Yapie: User', with a linked account
        (the main one or an additional one)."""
        self.ensure_one()
        u = self.sudo()
        return bool(u.active and (u.yapie_uid or u.yapie_extra_link_ids) and not u.share and u.has_group("yapie.group_yapie_user"))

    @api.model
    def _yapie_by_uid(self, uid):
        if not uid:
            return self.browse()
        user = self.sudo().search([("yapie_uid", "=", int(uid))], limit=1)
        if not user:
            user = self.env["yapie.user.link"].sudo().search([("yapie_uid", "=", int(uid))], limit=1).user_id.filtered("active")
        return user

    @api.model
    def _yapie_link_by_uid(self, uid):
        """The additional-account record for a Yapie account ID (empty for a user's main link)."""
        Link = self.env["yapie.user.link"].sudo()
        return Link.search([("yapie_uid", "=", int(uid))], limit=1) if uid else Link

    def _yapie_targets(self):
        """Every Yapie account this user is reached on: the main link first, then the additional ones."""
        self.ensure_one()
        u = self.sudo()
        out = []
        if u.yapie_chat_id:
            out.append({"chat_id": u.yapie_chat_id})
        elif u.yapie_target:
            out.append({"to": u.yapie_target})
        out += [link.target() for link in u.yapie_extra_link_ids]
        return out

    def _yapie_accounts(self):
        """[(handle Yapie knows the account by, where to send)] for the main link and every additional account."""
        self.ensure_one()
        u = self.sudo()
        out = []
        if u.yapie_target:
            out.append((u.yapie_target, {"chat_id": u.yapie_chat_id} if u.yapie_chat_id else {"to": u.yapie_target}))
        out += [(link.yapie_target, link.target()) for link in u.yapie_extra_link_ids]
        return out

    def _yapie_approver_handles(self):
        """What Yapie knows each account by, for an approval card (main link + additional accounts)."""
        self.ensure_one()
        return [h for h, _t in self._yapie_accounts() if h]

    def action_yapie_add_account(self):
        self.ensure_one()
        self._yapie_check_self_or_manager()
        return {"type": "ir.actions.act_window", "res_model": "yapie.link.wizard", "view_mode": "form", "target": "new",
                "name": _("Add another Yapie account"), "context": {"default_user_id": self.id, "default_extra": True}}

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
