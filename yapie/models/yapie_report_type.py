from odoo import api, fields, models


class YapieReportType(models.Model):
    """A report people can get in Yapie, and who may get it. Reports always run with the person's own Odoo
    access rights on top of this, so nobody sees records Odoo wouldn't show them."""
    _name = "yapie.report.type"
    _description = "Yapie report"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, readonly=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Char(translate=True)
    keywords = fields.Char(required=True, help="Words that ask for this report in chat, comma separated (first one is shown in the menu).")
    example = fields.Char(help="Shown in the chat menu")
    needs_partner = fields.Selection([("no", "No"), ("optional", "Optional"), ("required", "Required")], default="no", required=True)
    requires_model = fields.Char(readonly=True, help="Only available when this model exists (its app is installed)")
    available = fields.Boolean(compute="_compute_available")
    default_period = fields.Selection([
        ("this_month", "This month"), ("this_year", "This (fiscal) year"), ("as_of_today", "As of today"),
    ], default="this_month", required=True)
    group_ids = fields.Many2many("res.groups", string="Allowed groups")
    user_ids = fields.Many2many("res.users", string="Allowed people", domain=[("share", "=", False)])

    _code_unique = models.Constraint("UNIQUE(code)", "Report codes are unique.")

    @api.depends("requires_model")
    def _compute_available(self):
        for t in self:
            t.available = not t.requires_model or t.requires_model in self.env

    def allowed_for(self, user):
        """Yapie administrators, the listed people, and members of the listed groups."""
        self.ensure_one()
        user = user.sudo()
        if not (self.active and self.available and user._yapie_authorized()):
            return False
        if user.has_group("yapie.group_yapie_manager") or user in self.sudo().user_ids:
            return True
        return bool(self.sudo().group_ids & user.all_group_ids)

    @api.model
    def allowed_list(self, user):
        return self.sudo().search([]).filtered(lambda t: t.allowed_for(user))

    def keyword_list(self):
        self.ensure_one()
        return [k.strip().lower() for k in (self.keywords or "").split(",") if k.strip()]
