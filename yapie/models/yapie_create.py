import re
from datetime import date

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.safe_eval import safe_eval

ASKABLE = ("char", "text", "integer", "float", "monetary", "boolean", "date", "selection", "many2one")


class YapieCreateType(models.Model):
    """Something people may create from Yapie chat ("create account", "create customer"): which Odoo record, which
    fields the bot asks for, fixed values, and who may do it. The record is created as the person's Odoo user, so
    Odoo's own access rights apply on top; matching approval rules send it for approval at once."""
    _name = "yapie.create.type"
    _description = "Yapie: what can be created"
    _order = "sequence, id"

    name = fields.Char(required=True, help="What people see, e.g. 'Account (Chart of Accounts)'")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    keywords = fields.Char(required=True, help="Comma separated words after 'create', e.g. 'account, gl account'")
    model_id = fields.Many2one("ir.model", "Record type", required=True, ondelete="cascade", domain=[("transient", "=", False)])
    model = fields.Char(related="model_id.model", store=True)
    field_line_ids = fields.One2many("yapie.create.field", "type_id", "Fields the bot asks for", copy=True)
    fixed_values = fields.Char("Fixed values", default="{}",
                               help="Values always set, as a Python dict, e.g. {'move_type': 'out_invoice'}")
    user_ids = fields.Many2many("res.users", "yapie_create_type_user_rel", "type_id", "user_id", "Allowed people",
                                domain=[("share", "=", False)])
    group_ids = fields.Many2many("res.groups", "yapie_create_type_group_rel", "type_id", "group_id", "Allowed groups")
    send_for_approval = fields.Boolean("Send for approval", default=True,
                                       help="When an approval rule matches the new record, send it for approval at once.")

    @api.constrains("fixed_values")
    def _check_fixed(self):
        for t in self:
            if not isinstance(t._fixed(), dict):
                raise ValidationError(_("Fixed values must be a Python dict."))

    def _fixed(self):
        self.ensure_one()
        try:
            return safe_eval(self.fixed_values or "{}")
        except Exception as e:  # noqa: BLE001
            raise ValidationError(_("Fixed values: %s") % e) from e

    def keyword_list(self):
        self.ensure_one()
        return [k.strip().lower() for k in (self.keywords or "").split(",") if k.strip()]

    def allowed_for(self, user):
        """Listed people / groups (or Yapie administrators), Odoo's own create right on the record type, and -
        from an additional Yapie account - that person's role."""
        self.ensure_one()
        user = user.sudo()
        if not (self.active and self.model in self.env and user._yapie_authorized()):
            return False
        link_id = self.env.context.get("yapie_link_id")
        if link_id and not self.env["yapie.user.link"].sudo().browse(link_id).allows_create(self):
            return False
        if not (user.has_group("yapie.group_yapie_manager") or user in self.sudo().user_ids or self.sudo().group_ids & user.all_group_ids):
            return False
        return self.env[self.model].with_user(user).has_access("create")

    @api.model
    def allowed_list(self, user):
        return self.sudo().search([]).filtered(lambda t: t.allowed_for(user))

    def action_add_required_fields(self):
        """Add every field Odoo requires that has no default and isn't listed yet."""
        for t in self:
            Model = self.env[t.model]
            defaults = Model.default_get(list(Model._fields))
            have = set(t.field_line_ids.mapped("field_id.name")) | set(t._fixed())
            seq = max(t.field_line_ids.mapped("sequence") or [0])
            for name, f in Model._fields.items():
                if f.required and not f.compute and not f.related and f.type in ASKABLE and name not in have and name not in defaults:
                    seq += 10
                    t.field_line_ids = [(0, 0, {"field_id": self.env["ir.model.fields"]._get(t.model, name).id, "required": True, "sequence": seq})]
        return True


class YapieCreateField(models.Model):
    _name = "yapie.create.field"
    _description = "Yapie: field asked when creating"
    _order = "sequence, id"

    type_id = fields.Many2one("yapie.create.type", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    field_id = fields.Many2one("ir.model.fields", required=True, ondelete="cascade",
                               domain="[('model_id', '=', parent.model_id), ('ttype', 'in', %s), ('store', '=', True)]" % (list(ASKABLE),))
    prompt = fields.Char("Question", help="What the bot asks. Empty: the field's name")
    required = fields.Boolean(default=True)

    def question(self):
        self.ensure_one()
        f = self.field_id
        q = self.prompt or f.field_description
        hint = {"date": _(" (e.g. 28/11/2026 or today)"), "boolean": _(" (yes / no)")}.get(f.ttype, "")
        if f.ttype == "selection":
            opts = self.env[f.model]._fields[f.name]._description_selection(self.env)
            hint = "\n" + "\n".join("%d. %s" % (i + 1, label) for i, (_v, label) in enumerate(opts))
        if not self.required:
            hint += _("  — or “skip”")
        return "%s?%s" % (q, hint)

    def parse(self, text, user):
        """(value, display, choices). choices = [(id, name)] when a look-up needs the person to pick one."""
        self.ensure_one()
        f = self.field_id
        t = (text or "").strip()
        low = t.lower()
        if f.ttype in ("char", "text"):
            if not t:
                raise UserError(_("Please type a value."))
            return t, t, None
        if f.ttype in ("integer", "float", "monetary"):
            n = re.sub(r"[,\s]", "", t)
            try:
                v = int(n) if f.ttype == "integer" else float(n)
            except ValueError:
                raise UserError(_("Please send a number.")) from None
            return v, t, None
        if f.ttype == "boolean":
            if low in ("yes", "y", "true", "1", "haan", "ha"):
                return True, _("Yes"), None
            if low in ("no", "n", "false", "0", "nahi"):
                return False, _("No"), None
            raise UserError(_("Please answer yes or no."))
        if f.ttype == "date":
            if low in ("today", "aaj"):
                d = fields.Date.context_today(user.with_context(tz=user.tz))
            else:
                m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})$", t)
                if not m:
                    raise UserError(_("Please send the date like 28/11/2026."))
                dd, mm, yy = (int(x) for x in m.groups())
                try:
                    d = date(yy + 2000 if yy < 100 else yy, mm, dd)
                except ValueError:
                    raise UserError(_("That date doesn't exist.")) from None
            return fields.Date.to_string(d), d.strftime("%d/%m/%Y"), None
        if f.ttype == "selection":
            opts = self.env[f.model]._fields[f.name]._description_selection(self.env)
            if low.isdigit() and 1 <= int(low) <= len(opts):
                v, label = opts[int(low) - 1]
                return v, label, None
            hit = [o for o in opts if o[1].lower() == low or str(o[0]).lower() == low] or [o for o in opts if low in o[1].lower()]
            if len(hit) == 1:
                return hit[0][0], hit[0][1], None
            raise UserError(_("Please reply with the number of one of the choices."))
        if f.ttype == "many2one":
            Comodel = self.env[f.relation].with_user(user)
            found = Comodel.name_search(t, limit=9)
            if not found:
                raise UserError(_("I couldn't find “%s”. Send part of the name.") % t)
            exact = [r for r in found if r[1].lower() == low]
            if len(found) == 1 or len(exact) == 1:
                r = exact[0] if len(exact) == 1 else found[0]
                return r[0], r[1], None
            return None, None, [(r[0], r[1]) for r in found]
        raise UserError(_("This field can't be filled from Yapie."))
