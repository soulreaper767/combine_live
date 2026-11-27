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
    # this person's own part (chain of command): never more than the Odoo user may do, often less
    # a new person gets nothing until a Yapie administrator gives it to them
    report_access = fields.Selection([("none", "No reports"), ("selected", "Only the reports below"), ("all", "All the Odoo user's reports")],
                                     "Reports", default="none", required=True)
    report_type_ids = fields.Many2many("yapie.report.type", "yapie_user_link_report_rel", "link_id", "type_id", "Allowed reports",
                                       help="Used with 'Only the reports below'.")
    can_approve = fields.Boolean("May approve", default=False,
                                 help="Gets approval cards and may approve / reject for this Odoo user. Off = never decides anything.")
    approval_rule_ids = fields.Many2many("yapie.approval.rule", "yapie_user_link_rule_rel", "link_id", "rule_id", "Approvals",
                                         help="Approval rules this person decides. Empty = every rule the Odoo user approves.")
    create_access = fields.Selection([("none", "Can't create"), ("selected", "Only the types below"), ("all", "All the Odoo user may create")],
                                     "Create from chat", default="none", required=True)
    create_type_ids = fields.Many2many("yapie.create.type", "yapie_user_link_create_rel", "link_id", "type_id", "May create",
                                       help="Used with 'Only the types below'.")
    receive_alerts = fields.Boolean("Gets review alerts", default=False)
    receive_schedules = fields.Boolean("Gets scheduled reports", default=False,
                                       help="Only the scheduled reports this person may also ask for.")
    log_count = fields.Integer("Activity", compute="_compute_log_count")

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

    ROLE_FIELDS = {"report_access", "report_type_ids", "can_approve", "approval_rule_ids", "receive_alerts", "receive_schedules",
                   "create_access", "create_type_ids"}

    def allows_create(self, ctype):
        self.ensure_one()
        return self.create_access == "all" or (self.create_access == "selected" and ctype in self.create_type_ids)

    def _compute_log_count(self):
        Log = self.env["yapie.log"].sudo()
        for link in self:
            link.log_count = Log.search_count([("link_id", "=", link.id)])

    def allows_report(self, rtype):
        self.ensure_one()
        return self.report_access == "all" or (self.report_access == "selected" and rtype in self.report_type_ids)

    def allows_approval(self, rule=None):
        self.ensure_one()
        return self.can_approve and (not self.approval_rule_ids or not rule or rule in self.approval_rule_ids)

    def write(self, vals):
        # the account itself is only set by the link wizard (one-time code); the person's role is set by a
        # Yapie administrator; the user may only rename the label
        if set(vals) - {"person"} - self.ROLE_FIELDS and not self.env.su:
            raise AccessError(_("Yapie accounts are linked with the one-time code (Add another Yapie account)."))
        if set(vals) & self.ROLE_FIELDS and not self.env.su and not self.env.user.has_group("yapie.group_yapie_manager"):
            raise AccessError(_("Only a Yapie administrator sets what each person may do."))
        return super().write(vals)

    def action_view_activity(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "res_model": "yapie.log", "view_mode": "list", "name": _("Activity of %s") % self.label(),
                "domain": [("link_id", "=", self.id)]}

    def action_unlink_account(self):
        for link in self:
            link.user_id._yapie_check_self_or_manager()
            self.env["yapie.log"].sudo().add("link", _("%(u)s: Yapie account %(p)s unlinked", u=link.user_id.name, p=link.label()), user=link.user_id)
        self.sudo().unlink()
        return True
