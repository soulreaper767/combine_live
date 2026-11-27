from odoo import api, fields, models


class YapieLog(models.Model):
    """Everything that went to or came from Yapie: who asked for what, what was sent, who was refused."""
    _name = "yapie.log"
    _description = "Yapie activity"
    _order = "id desc"
    _rec_name = "summary"

    kind = fields.Selection([
        ("link", "Linking"), ("command", "Chat request"), ("report", "Report sent"), ("schedule", "Scheduled report"),
        ("approval", "Approval"), ("notify", "Review alert"), ("denied", "Refused"), ("attendance", "Attendance"),
        ("error", "Error"), ("create", "Created from chat"),
    ], required=True, index=True, readonly=True)
    user_id = fields.Many2one("res.users", readonly=True, index=True, ondelete="set null")
    yapie_name = fields.Char("Yapie person", readonly=True)
    summary = fields.Char(readonly=True)
    state = fields.Selection([("ok", "Done"), ("error", "Failed")], default="ok", readonly=True)
    res_model = fields.Char(readonly=True)
    res_id = fields.Integer(readonly=True)
    rule_ref = fields.Char(readonly=True, index=True, help="Internal: which rule/schedule produced it")
    # which Yapie account did it (several people can work through one Odoo user)
    yapie_uid = fields.Integer("Yapie account ID", readonly=True, index=True)
    yapie_account = fields.Char("Yapie account", readonly=True, index=True,
                                help="The Yapie account that did it: the user's main account or one of their additional accounts.")
    link_id = fields.Many2one("yapie.user.link", "Additional account", readonly=True, ondelete="set null", index=True)

    @api.model
    def add(self, kind, summary, user=None, state="ok", yapie_name=None, record=None, rule_ref=None, account=None):
        # the acting Yapie account comes from the conversation / decision being handled (context), unless given
        account = account or self.env.context.get("yapie_account") or {}
        return self.sudo().create({
            "kind": kind, "summary": (summary or "")[:500], "state": state, "user_id": user.id if user else False,
            "yapie_name": yapie_name, "res_model": record._name if record else False, "res_id": record.id if record else 0,
            "rule_ref": rule_ref, "yapie_uid": account.get("uid") or 0, "yapie_account": account.get("label") or False,
            "link_id": account.get("link_id") or False,
        })

    @api.autovacuum
    def _gc_old(self):
        self.sudo().search([("create_date", "<", fields.Datetime.subtract(fields.Datetime.now(), days=365))]).unlink()
