import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tools.safe_eval import safe_eval

from .yapie_approval import doc_link, field_value, users_of

_logger = logging.getLogger(__name__)


class YapieNotifyRule(models.Model):
    """'X is ready for your review': tell the right people on Yapie when a document starts meeting a condition
    (e.g. a vendor bill is created, a quotation is sent, a delivery is ready). Each person gets it only if they are
    linked, authorised, and can open that document in Odoo. Optionally also tells the document's customer."""
    _name = "yapie.notify.rule"
    _description = "Yapie review alert"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    model_id = fields.Many2one("ir.model", "Document type", required=True, ondelete="cascade", domain=[("transient", "=", False)])
    model = fields.Char(related="model_id.model", store=True)
    domain = fields.Char("When", default="[]", help="Sent when a document starts matching this (on creation or after a change)")
    message = fields.Char(default="{document} is ready for your review", required=True,
                          help="{document} = the document's name, {type} = its type")
    user_ids = fields.Many2many("res.users", "yapie_notify_user_rel", "rule_id", "user_id", "People", domain=[("share", "=", False)])
    group_ids = fields.Many2many("res.groups", "yapie_notify_group_rel", "rule_id", "group_id", "Groups")
    user_field_ids = fields.Many2many("ir.model.fields", "yapie_notify_field_rel", "rule_id", "field_id", "People on the document",
                                      domain="[('model_id', '=', model_id), ('relation', '=', 'res.users'), ('ttype', 'in', ('many2one', 'many2many'))]",
                                      help="e.g. Salesperson, Responsible")
    chat_id = fields.Many2one("yapie.chat", "Also post in group")
    partner_field_id = fields.Many2one("ir.model.fields", "Also tell the customer",
                                       domain="[('model_id', '=', model_id), ('relation', '=', 'res.partner'), ('ttype', '=', 'many2one')]",
                                       help="The contact on the document (reached on Yapie by mobile or email). They get the message about their "
                                            "own document only.")
    partner_message = fields.Char("Customer message", default="{document}: update from {company}")
    field_ids = fields.Many2many("ir.model.fields", "yapie_notify_show_rel", "rule_id", "field_id", "Show",
                                 domain="[('model_id', '=', model_id), ('ttype', 'not in', ('one2many', 'binary', 'html'))]")
    automation_id = fields.Many2one("base.automation", readonly=True, copy=False, ondelete="set null")

    def _domain_list(self):
        self.ensure_one()
        return safe_eval(self.domain or "[]", {"uid": self.env.uid, "user": self.env.user})

    def _sync_hooks(self):
        for rule in self:
            dom = rule._domain_list()
            vals = {"name": _("Yapie: %s") % rule.name, "model_id": rule.model_id.id, "trigger": "on_create_or_write",
                    "filter_domain": repr(list(Domain(dom))), "filter_pre_domain": repr(list(~Domain(dom))), "active": rule.active}
            if rule.automation_id:
                rule.automation_id.sudo().write(vals)
            else:
                auto = self.env["base.automation"].sudo().create(vals)
                self.env["ir.actions.server"].sudo().create({
                    "name": vals["name"], "model_id": rule.model_id.id, "state": "code", "usage": "base_automation",
                    "base_automation_id": auto.id, "code": "env['yapie.notify.rule'].browse(%d)._fire(records)" % rule.id})
                rule.automation_id = auto

    @api.model_create_multi
    def create(self, vals_list):
        rules = super().create(vals_list)
        rules._sync_hooks()
        return rules

    def write(self, vals):
        res = super().write(vals)
        if {"model_id", "domain", "active", "name"} & set(vals):
            self._sync_hooks()
        return res

    def unlink(self):
        autos = self.mapped("automation_id")
        res = super().unlink()
        autos.sudo().unlink()
        return res

    def _recipients(self, rec):
        users = users_of(self.user_ids, self.group_ids)
        for f in self.user_field_ids:
            users |= rec.sudo()[f.name]
        # linked, authorised, and allowed to open this document
        return users.filtered(lambda u: u.active and u._yapie_authorized() and rec.with_user(u).has_access("read"))

    def _text(self, rec, template, fields_):
        doc = rec.display_name
        text = (template or "").replace("{document}", doc).replace("{type}", rec._description).replace("{company}", rec.env.company.name)
        lines = ["📄 " + text]
        for f in fields_:
            v = field_value(rec.sudo(), f)
            if v:
                lines.append("%s: %s" % (f.field_description, v))
        return "\n".join(lines)

    def _fire(self, records):
        self = self.sudo()
        if not self.active or not records:
            return
        api_ = self.env["yapie.api"]
        if not api_.is_configured():
            return
        for rec in records:
            try:
                users = self._recipients(rec)
                body = self._text(rec, self.message, self.field_ids) + "\n" + doc_link(rec)
                sent = []
                for u in users:
                    api_.send_later(api_.target_of(u), body)
                    sent.append(u.name)
                if self.chat_id and self.chat_id.safe_for(lambda u: rec.with_user(u).has_access("read")):
                    api_.send_later({"chat_id": self.chat_id.chat_id}, body)
                    sent.append(self.chat_id.name)
                if self.partner_field_id:
                    partner = rec.sudo()[self.partner_field_id.name]
                    to = (getattr(partner, "mobile", False) or partner.phone or partner.email or "").strip() if partner else ""
                    if to:
                        api_.send_later({"to": to}, self._text(rec, self.partner_message, self.env["ir.model.fields"]))
                        sent.append(partner.display_name)
                if sent:
                    self.env["yapie.log"].add("notify", _("%(r)s: %(d)s → %(who)s", r=self.name, d=rec.display_name, who=", ".join(sent)), record=rec, rule_ref="notify:%s" % self.id)
            except Exception as e:  # noqa: BLE001  never block saving the document
                _logger.warning("Yapie alert %s failed: %s", self.name, e)
                self.env["yapie.log"].add("notify", _("%(r)s: %(d)s — %(e)s", r=self.name, d=rec.display_name, e=str(e)[:200]), record=rec, state="error")

    def action_test(self):
        self.ensure_one()
        rec = self.env[self.model].search(self._domain_list(), limit=1, order="id desc")
        if not rec:
            raise UserError(_("No %s matches the condition yet.") % self.model_id.name)
        self._fire(rec)
        return {"type": "ir.actions.client", "tag": "display_notification",
                "params": {"title": _("Yapie"), "message": _("Sent for %s (see Yapie › Activity).") % rec.display_name, "type": "info"}}
