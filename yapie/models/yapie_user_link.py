from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class YapieUserLink(models.Model):
    """More Yapie accounts on ONE Odoo user: several people (each with their own Yapie) work through one Odoo
    login. Each account is proved with the same one-time code as the main link; whatever any of them asks or
    approves on Yapie is done as that Odoo user, with exactly that user's rights."""
    _name = "yapie.user.link"
    _description = "Additional Yapie account"
    _order = "user_id, id"

    user_id = fields.Many2one("res.users", "Odoo user", required=True, ondelete="cascade", index=True, readonly=True)
    person = fields.Char("Person", help="Who uses this Yapie account, e.g. 'Ali – store'. Shown in the chatter when they approve.")
    yapie_uid = fields.Integer("Yapie account ID", required=True, readonly=True, index=True, copy=False)
    yapie_target = fields.Char("Linked with", readonly=True, copy=False)
    yapie_username = fields.Char("Yapie username", readonly=True, copy=False)
    yapie_chat_id = fields.Integer("Chat with the bot", readonly=True, copy=False)
    yapie_linked_at = fields.Datetime("Linked on", readonly=True, copy=False)

    _uid_unique = models.Constraint("UNIQUE(yapie_uid)", "This Yapie account is already linked.")

    @api.constrains("yapie_uid")
    def _check_not_main_link(self):
        Users = self.env["res.users"].sudo().with_context(active_test=False)
        for link in self:
            if Users.search_count([("yapie_uid", "=", link.yapie_uid)]):
                raise ValidationError(_("This Yapie account is already linked to an Odoo user."))

    def label(self):
        self.ensure_one()
        return self.person or (("@" + self.yapie_username) if self.yapie_username else self.yapie_target) or "?"

    def target(self):
        self.ensure_one()
        return {"chat_id": self.yapie_chat_id} if self.yapie_chat_id else {"to": self.yapie_target}

    def write(self, vals):
        # the account itself is only set by the link wizard (one-time code); people may only rename the label
        if set(vals) - {"person"} and not self.env.su:
            raise AccessError(_("Yapie accounts are linked with the one-time code (Add another Yapie account)."))
        return super().write(vals)

    def action_unlink_account(self):
        for link in self:
            link.user_id._yapie_check_self_or_manager()
            self.env["yapie.log"].sudo().add("link", _("%(u)s: Yapie account %(p)s unlinked", u=link.user_id.name, p=link.label()), user=link.user_id)
        self.sudo().unlink()
        return True
