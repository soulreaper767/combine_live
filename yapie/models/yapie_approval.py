import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)

# what "approve" / "reject" do for common documents (other models: fill in the method names)
DEFAULTS = {
    "sale.order": ("action_confirm", "action_cancel", ["partner_id", "amount_total", "user_id", "date_order"]),
    "purchase.order": ("button_confirm", "button_cancel", ["partner_id", "amount_total", "user_id", "date_order"]),
    "account.move": ("action_post", "button_cancel", ["partner_id", "amount_total", "invoice_date", "invoice_date_due"]),
    "account.payment": ("action_post", "action_cancel", ["partner_id", "amount", "date", "journal_id"]),
    "hr.expense.sheet": ("action_approve_expense_sheets", "action_refuse_expense_sheets", ["employee_id", "total_amount"]),
}


def users_of(rule_users, groups):
    users = rule_users
    for g in groups:
        users |= (g.all_user_ids if "all_user_ids" in g._fields else g.user_ids)
    return users.filtered(lambda u: u.active and not u.share)


def field_value(record, field):
    v = record[field.name]
    if field.ttype == "many2one":
        return v.display_name or ""
    if field.ttype == "monetary":
        cur_field = record._fields[field.name].get_currency_field(record) if hasattr(record._fields[field.name], "get_currency_field") else "currency_id"
        cur = record[cur_field] if cur_field and cur_field in record._fields else record.env.company.currency_id
        return "%s %s" % (cur.symbol or cur.name or "", "{:,.2f}".format(v or 0))
    if field.ttype == "selection":
        return dict(record._fields[field.name]._description_selection(record.env)).get(v, v or "")
    if field.ttype == "date":
        return fields.Date.to_string(v) if v else ""
    if field.ttype == "datetime":
        return fields.Datetime.to_string(v) if v else ""
    if field.ttype == "boolean":
        return _("Yes") if v else _("No")
    if field.ttype in ("many2many", "one2many"):
        return ", ".join(v.mapped("display_name"))[:200]
    return "" if v in (False, None) else str(v)


def _money(record, amount):
    cur = record["currency_id"] if "currency_id" in record._fields and record["currency_id"] else record.env.company.currency_id
    return "%s %s" % (cur.symbol or cur.name or "", "{:,.2f}".format(amount or 0))


def _num(v):
    return "{:,.2f}".format(v).rstrip("0").rstrip(".") if v else "0"


def doc_party(record):
    for f in ("partner_id", "employee_id"):
        if f in record._fields and record[f]:
            p = record[f]
            return (p.commercial_partner_id if "commercial_partner_id" in p._fields else p).display_name
    return ""


def doc_summary(record):
    """The main points of a document for an approval card: party, dates, references, people, the items and the
    totals - whatever of these the document has. [[label, value], ...]"""
    rec = record.sudo()
    out = []
    F = rec._fields
    IMF = rec.env["ir.model.fields"]
    party = doc_party(rec)
    if party:
        out.append([_("Party"), party])
    seen_dates = []
    for f in ("date_order", "invoice_date", "date", "invoice_date_due", "date_planned", "validity_date"):
        if f in F and rec[f] and len(seen_dates) < 2:
            day = field_value(rec, IMF._get(rec._name, f))[:10]  # a date is enough on a card
            if day not in seen_dates:
                out.append([F[f].string, day])
                seen_dates.append(day)
    for f in ("partner_ref", "client_order_ref", "ref", "origin", "payment_reference"):
        if f in F and rec[f] and rec[f] != rec.display_name:
            out.append([F[f].string, str(rec[f])[:80]])
    for f in ("invoice_user_id", "user_id"):
        if f in F and rec[f]:
            out.append([F[f].string, rec[f].display_name])
            break
    if "payment_term_id" in F and rec.payment_term_id:
        out.append([F["payment_term_id"].string, rec.payment_term_id.display_name])
    lines = None
    for f in ("order_line", "invoice_line_ids", "expense_line_ids"):
        if f in F and F[f].type == "one2many":
            lines = rec[f]
            break
    if lines:
        items = lines.filtered(lambda l: not getattr(l, "display_type", False) or l.display_type == "product")
        for i, l in enumerate(items[:6], 1):
            name = (l.product_id.display_name if "product_id" in l._fields and l.product_id else (l.name or ""))[:60]
            qty = next((l[q] for q in ("product_uom_qty", "product_qty", "quantity") if q in l._fields), 0)
            uom = next((l[u].name for u in ("product_uom_id", "product_uom") if u in l._fields and l[u]), "")
            price = l.price_unit if "price_unit" in l._fields else 0
            sub = l.price_subtotal if "price_subtotal" in l._fields else 0
            text = "%s %s %s @ %s = %s" % (name, _num(qty), uom, _num(price), _money(rec, sub)) if qty else name
            out.append([_("Item %s") % i, " ".join(text.split())])
        if len(items) > 6:
            out.append([_("More items"), _("%s more line(s)") % (len(items) - 6)])
    if "amount_untaxed" in F and "amount_tax" in F and rec.amount_tax:
        out.append([F["amount_untaxed"].string, _money(rec, rec.amount_untaxed)])
        out.append([F["amount_tax"].string, _money(rec, rec.amount_tax)])
    for f in ("amount_total", "amount", "total_amount"):
        if f in F and rec[f]:
            out.append([_("Total"), _money(rec, rec[f])])
            break
    return out


def doc_link(record):
    base = record.env["ir.config_parameter"].sudo().get_param("web.base.url", "").rstrip("/")
    return "%s/odoo/%s/%s" % (base, record._name, record.id)


class YapieApprovalRule(models.Model):
    """Which documents need approval on Yapie, who may send them for approval, who approves, and what approving does."""
    _name = "yapie.approval.rule"
    _description = "Yapie approval rule"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    model_id = fields.Many2one("ir.model", "Document type", required=True, ondelete="cascade", domain=[("transient", "=", False)])
    model = fields.Char(related="model_id.model", store=True)
    domain = fields.Char("Applies when", default="[]", help="Only documents matching this need this approval (e.g. amount over 100,000)")
    approver_user_ids = fields.Many2many("res.users", "yapie_rule_approver_rel", "rule_id", "user_id", "Approvers", domain=[("share", "=", False)])
    approver_group_ids = fields.Many2many("res.groups", "yapie_rule_approver_group_rel", "rule_id", "group_id", "Approver groups")
    requester_user_ids = fields.Many2many("res.users", "yapie_rule_requester_rel", "rule_id", "user_id", "Who may send for approval",
                                          domain=[("share", "=", False)], help="Empty (and no groups): anyone who can edit the document")
    requester_group_ids = fields.Many2many("res.groups", "yapie_rule_requester_group_rel", "rule_id", "group_id", "Groups who may send")
    chat_id = fields.Many2one("yapie.chat", "Post in group", help="Post one card in this Yapie group instead of one to each approver "
                                                                   "(only if every member is an authorised approver-side user)")
    field_ids = fields.Many2many("ir.model.fields", string="Show on the card",
                                 domain="[('model_id', '=', model_id), ('ttype', 'not in', ('one2many', 'binary', 'html'))]")
    approve_method = fields.Char("When approved, run", help="Method on the document, e.g. action_confirm. Runs as the approver.")
    reject_method = fields.Char("When rejected, run", help="Optional, e.g. action_cancel. Empty: only logged")
    due_hours = fields.Integer("Remind after (hours)", default=24)
    auto_request = fields.Boolean("Ask automatically", help="Send for approval as soon as a document starts matching the condition")
    notify_requester = fields.Boolean("Tell the requester the decision", default=True)
    automation_id = fields.Many2one("base.automation", readonly=True, copy=False, ondelete="set null")
    action_id = fields.Many2one("ir.actions.server", readonly=True, copy=False, ondelete="set null")
    request_count = fields.Integer(compute="_compute_request_count")
    # ---- rules that follow an Odoo approval workflow (yapie.workflow); set by the sync, not by hand ----
    workflow_key = fields.Char("Follows Odoo workflow", readonly=True, copy=False, index=True,
                               help="Set by “Sync with Odoo workflows”: documents, approvers, mode and buttons come from Odoo's own "
                                    "approval workflow, so Yapie and Odoo can never disagree.")
    approval_mode = fields.Selection([("any", "Any one approver decides"), ("all", "Every approver must approve")],
                                     "Approved by", default="any", required=True)
    reason_field = fields.Char("Rejection reason field", help="Field on the document the rejection reason is written to before the "
                                                               "reject button runs (e.g. x_rejection_reason).")

    @api.constrains("model_id", "active", "workflow_key")
    def _check_no_clash_with_workflow(self):
        for r in self.filtered(lambda r: r.active and not r.workflow_key):
            synced = self.sudo().search([("workflow_key", "!=", False), ("model", "=", r.model), ("active", "=", True)], limit=1)
            if synced:
                raise ValidationError(_("%(m)s follows Odoo's own approval workflow (rule “%(s)s”). A separate Yapie rule would send "
                                        "cards to different people than Odoo expects, so it isn't allowed. Change the approvers in Odoo "
                                        "and press “Sync with Odoo workflows”.", m=r.model_id.name, s=synced.name))


    @api.model
    def _yapie_sync_workflows(self):
        """Create / update one rule per Odoo approval workflow, switch off rules whose workflow is gone, and switch off manual
        rules on the same document types (their pending requests are withdrawn) so Yapie never contradicts Odoo."""
        Rule = self.sudo().with_context(active_test=False, yapie_workflow_sync=True)
        seen = Rule.browse()
        log = []
        for wf in self.env["yapie.workflow"].sudo()._yapie_workflows():
            if wf["model"] not in self.env:
                continue
            groups = self.env["res.groups"]
            for xid in wf.get("groups", []):
                groups |= self.env.ref(xid, raise_if_not_found=False) or self.env["res.groups"]
            vals = {"name": wf["name"], "model_id": self.env["ir.model"]._get(wf["model"]).id, "domain": repr(wf["domain"]),
                    "approver_group_ids": [(6, 0, groups.ids)], "approver_user_ids": [(6, 0, wf.get("user_ids", []))],
                    "approve_method": wf["approve"], "reject_method": wf.get("reject") or False, "approval_mode": wf.get("mode", "any"),
                    "reason_field": wf.get("reason_field") or False, "auto_request": True, "active": True, "workflow_key": wf["key"]}
            rule = Rule.search([("workflow_key", "=", wf["key"])], limit=1)
            if rule:
                rule.write(vals)
            else:
                rule = Rule.create(vals)
                log.append(_("added %s") % wf["name"])
            seen |= rule
        for rule in Rule.search([("workflow_key", "!=", False), ("id", "not in", seen.ids), ("active", "=", True)]):
            rule.active = False
            log.append(_("switched off %s (workflow no longer in Odoo)") % rule.name)
        Req = self.env["yapie.approval.request"].sudo()
        for rule in Rule.search([("workflow_key", "=", False), ("model", "in", seen.mapped("model")), ("active", "=", True)]):
            for req in Req.search([("rule_id", "=", rule.id), ("state", "=", "pending")]):
                req._yapie_close(_("Withdrawn: this document type now follows Odoo's approval workflow"))
            rule.active = False
            log.append(_("switched off manual rule %s (Odoo's workflow decides these documents)") % rule.name)
        if log:
            self.env["yapie.log"].add("approval", _("Synced with Odoo workflows: %s") % "; ".join(log))
        return log

    def action_sync_workflows(self):
        log = self._yapie_sync_workflows()
        return {"type": "ir.actions.client", "tag": "display_notification",
                "params": {"title": _("Synced with Odoo workflows"), "message": "; ".join(log) or _("Already in step with Odoo."),
                           "type": "success", "next": {"type": "ir.actions.client", "tag": "soft_reload"}}}

    def _compute_request_count(self):
        data = dict(self.env["yapie.approval.request"]._read_group([("rule_id", "in", self.ids)], ["rule_id"], ["__count"]))
        for r in self:
            r.request_count = data.get(r, 0)

    @api.onchange("model_id")
    def _onchange_model(self):
        d = DEFAULTS.get(self.model_id.model)
        if d:
            self.approve_method, self.reject_method = d[0], d[1]
            self.field_ids = self.env["ir.model.fields"].search([("model", "=", self.model_id.model), ("name", "in", d[2])])
        if self.model_id and not self.name:
            self.name = _("Approve %s") % self.model_id.name

    @api.constrains("approve_method", "reject_method", "model_id")
    def _check_methods(self):
        for r in self:
            Model = self.env[r.model]
            for m in (r.approve_method, r.reject_method):
                if m and (m.startswith("_") or not callable(getattr(Model, m, None))):
                    raise ValidationError(_("%(m)s isn't a public action of %(model)s.", m=m, model=r.model_id.name))

    def _domain_list(self):
        self.ensure_one()
        return safe_eval(self.domain or "[]", {"uid": self.env.uid, "user": self.env.user})

    def approvers(self):
        """Approvers who can actually decide: linked and authorised."""
        self.ensure_one()
        return users_of(self.approver_user_ids, self.approver_group_ids).filtered(lambda u: u._yapie_authorized())

    def can_request(self, user, record):
        self.ensure_one()
        if user.has_group("yapie.group_yapie_manager"):
            return True
        if self.requester_user_ids or self.requester_group_ids:
            return user in users_of(self.requester_user_ids, self.requester_group_ids)
        return record.with_user(user).has_access("write")

    def matches(self, records):
        self.ensure_one()
        return records.filtered_domain(self._domain_list())

    # ---------- the Action-menu entry and the automatic trigger ----------
    def _sync_hooks(self):
        for rule in self:
            vals = {"name": _("Request approval on Yapie"), "model_id": rule.model_id.id, "binding_model_id": rule.model_id.id,
                    "state": "code", "code": "action = env['yapie.approval.request']._open_wizard(records)"}
            if rule.action_id:
                rule.action_id.write(vals)
            else:
                rule.action_id = self.env["ir.actions.server"].sudo().create(vals)
            want = rule.active and rule.auto_request
            if want:
                dom = rule._domain_list()
                avals = {"name": _("Yapie: ask for approval — %s") % rule.name, "model_id": rule.model_id.id, "trigger": "on_create_or_write",
                         "filter_domain": repr(list(Domain(dom))), "filter_pre_domain": repr(list(~Domain(dom))), "active": True}
                if rule.automation_id:
                    rule.automation_id.sudo().write(avals)
                else:
                    auto = self.env["base.automation"].sudo().create(avals)
                    self.env["ir.actions.server"].sudo().create({
                        "name": avals["name"], "model_id": rule.model_id.id, "state": "code", "usage": "base_automation",
                        "base_automation_id": auto.id, "code": "env['yapie.approval.request']._auto_request(records, %d)" % rule.id})
                    rule.automation_id = auto
            elif rule.automation_id:
                rule.automation_id.sudo().active = False

    @api.model_create_multi
    def create(self, vals_list):
        rules = super().create(vals_list)
        rules._sync_hooks()
        return rules

    def write(self, vals):
        locked = {"model_id", "domain", "approver_user_ids", "approver_group_ids", "approve_method", "reject_method", "approval_mode",
                  "reason_field", "auto_request", "workflow_key"}
        if locked & set(vals) and not self.env.context.get("yapie_workflow_sync") and any(r.workflow_key for r in self):
            raise ValidationError(_("This rule follows an Odoo approval workflow: its documents, approvers and buttons come from Odoo. "
                                    "Change them in Odoo, then press “Sync with Odoo workflows”."))
        res = super().write(vals)
        if {"model_id", "domain", "auto_request", "active", "name"} & set(vals):
            self._sync_hooks()
        return res

    def unlink(self):
        actions, autos = self.mapped("action_id"), self.mapped("automation_id")
        res = super().unlink()
        actions.sudo().unlink()
        autos.sudo().unlink()
        return res

    def action_view_requests(self):
        return {"type": "ir.actions.act_window", "res_model": "yapie.approval.request", "view_mode": "list,form",
                "domain": [("rule_id", "in", self.ids)], "name": _("Approval requests")}


class YapieApprovalRequest(models.Model):
    """One document sent for approval, and how it was decided."""
    _name = "yapie.approval.request"
    _description = "Yapie approval request"
    _order = "id desc"

    name = fields.Char(required=True, readonly=True)
    rule_id = fields.Many2one("yapie.approval.rule", ondelete="set null", readonly=True)
    res_model = fields.Char(required=True, index=True, readonly=True)
    res_id = fields.Integer(required=True, index=True, readonly=True)
    state = fields.Selection([("pending", "Waiting"), ("approved", "Approved"), ("rejected", "Rejected"), ("cancelled", "Withdrawn")],
                             default="pending", required=True, index=True, readonly=True)
    requested_by = fields.Many2one("res.users", default=lambda s: s.env.user, readonly=True)
    automatic = fields.Boolean(readonly=True)
    note = fields.Char(readonly=True)
    approver_ids = fields.Many2many("res.users", "yapie_request_approver_rel", "request_id", "user_id", readonly=True)
    card_ids = fields.One2many("yapie.approval.card", "request_id", readonly=True)
    decided_user_id = fields.Many2one("res.users", readonly=True)
    decided_at = fields.Datetime(readonly=True)
    comment = fields.Text(readonly=True)
    via = fields.Char(readonly=True)
    applied = fields.Selection([("ok", "Applied"), ("error", "Failed"), ("none", "Logged only")], readonly=True)
    applied_note = fields.Char(readonly=True)
    approved_user_ids = fields.Many2many("res.users", "yapie_request_approved_rel", "request_id", "user_id", "Approved so far", readonly=True,
                                         help="For rules where every approver must approve.")

    def _yapie_close(self, note):
        """Close a pending request without a Yapie decision (decided in Odoo, withdrawn, rule replaced): cards are withdrawn."""
        api_ = self.env["yapie.api"].sudo()
        for req in self.filtered(lambda r: r.state == "pending"):
            for card in req.card_ids.filtered(lambda c: c.state == "open"):
                try:
                    api_.call("/approvals/%s/cancel" % card.yapie_id, {})
                except UserError:
                    pass
                card.state = "closed"
            req.write({"state": "cancelled", "applied": "none", "applied_note": note[:180]})
            self.env["yapie.log"].add("approval", _("%(d)s: %(n)s", d=req.name, n=note))

    @api.model
    def _cron_close_decided_in_odoo(self):
        """A document approved / rejected inside Odoo no longer waits: withdraw its Yapie cards, so nobody acts on stale cards."""
        for req in self.sudo().search([("state", "=", "pending"), ("rule_id.workflow_key", "!=", False)]):
            rec = self.env[req.res_model].sudo().browse(req.res_id).exists() if req.res_model in self.env else None
            if not rec or not req.rule_id.matches(rec):
                req._yapie_close(_("Already decided in Odoo"))

    # ---------- asking ----------
    @api.model
    def _open_wizard(self, records):
        rules = self.env["yapie.approval.rule"].search([("model", "=", records._name)])
        if not rules:
            raise UserError(_("No Yapie approval rule for %s yet (Yapie › Approvals › Rules).") % records._description)
        return {"type": "ir.actions.act_window", "res_model": "yapie.approval.wizard", "view_mode": "form", "target": "new",
                "name": _("Request approval on Yapie"),
                "context": {"default_res_model": records._name, "default_res_ids": ",".join(map(str, records.ids)), "default_rule_id": rules[0].id}}

    @api.model
    def _auto_request(self, records, rule_id):
        rule = self.env["yapie.approval.rule"].sudo().browse(rule_id).exists()
        if not rule or not rule.active:
            return
        for rec in rule.matches(records):
            if self.sudo().search_count([("res_model", "=", rec._name), ("res_id", "=", rec.id), ("rule_id", "=", rule.id), ("state", "=", "pending")]):
                continue
            try:
                with self.env.cr.savepoint():
                    self.sudo().request(rec, rule, by=self.env.user, automatic=True)
            except Exception as e:  # noqa: BLE001  never block saving the document
                self.env["yapie.log"].add("approval", _("Could not ask for approval of %(d)s: %(e)s", d=rec.display_name, e=str(e)[:200]), state="error", record=rec)

    @api.model
    def request(self, records, rule, note=False, by=None, automatic=False):
        by = by or self.env.user
        api_ = self.env["yapie.api"].sudo()
        approvers = rule.approvers()
        if not approvers:
            raise UserError(_("Nobody can approve this yet: the rule's approvers must link Yapie (and be Yapie users)."))
        out = self.browse()
        for rec in records:
            if not automatic and not rule.can_request(by, rec):
                raise AccessError(_("You aren't allowed to send %s for approval.") % rec.display_name)
            if not rule.matches(rec):
                raise UserError(_("%(d)s doesn't need this approval (%(r)s).", d=rec.display_name, r=rule.name))
            if self.sudo().search_count([("res_model", "=", rec._name), ("res_id", "=", rec.id), ("state", "=", "pending")]):
                raise UserError(_("%s is already waiting for approval.") % rec.display_name)
            amount = ""
            if "amount_total" in rec._fields:
                amount = " — " + field_value(rec, self.env["ir.model.fields"]._get(rec._name, "amount_total"))
            party = doc_party(rec)
            title = ("%s %s%s%s" % (rec._description, rec.display_name, (" — " + party) if party else "", amount))[:200]
            # the rule's chosen fields first, then the document's main points (party, dates, references, items, totals)
            card_fields = [[f.field_description, field_value(rec.sudo(), f)] for f in rule.field_ids]
            chosen = {c[0] for c in card_fields}
            card_fields += [c for c in doc_summary(rec) if c[0] not in chosen]
            card_fields = card_fields[:24]
            names = ", ".join(approvers.mapped("name"))
            card_fields.append([_("Approval"), (_("Every one of: %s") if rule.approval_mode == "all" else
                                                _("Any one of: %s") if len(approvers) > 1 else "%s") % names])
            if note:
                card_fields.append([_("Note"), note])
            card_fields.append([_("Requested by"), by.name + (_(" (automatic)") if automatic else "")])
            req = self.sudo().create({"name": title, "rule_id": rule.id, "res_model": rec._name, "res_id": rec.id, "requested_by": by.id,
                                      "automatic": automatic, "note": note or False, "approver_ids": [(6, 0, approvers.ids)]})
            base = {"title": title, "system": "Odoo", "ref": "%s:%s" % (rec._name, rec.id), "fields": card_fields, "link": doc_link(rec),
                    "due_hours": rule.due_hours or None}
            # one card in a group whose members are all approvers, or one card to each approver privately
            if rule.chat_id and rule.chat_id.safe_for(lambda u: u in approvers):
                r = api_.call("/approvals", dict(base, chat_id=rule.chat_id.chat_id, approvers=[u.yapie_target for u in approvers]))
                self.env["yapie.approval.card"].sudo().create({"request_id": req.id, "yapie_id": r.get("approval_id"), "chat_id": rule.chat_id.id})
            else:
                for u in approvers:
                    r = api_.call("/approvals", dict(base, approvers=[u.yapie_target], **api_.target_of(u)))
                    self.env["yapie.approval.card"].sudo().create({"request_id": req.id, "yapie_id": r.get("approval_id"), "user_id": u.id})
            if hasattr(rec, "message_post"):
                rec.sudo().message_post(body=_("Sent for approval on Yapie to %s.") % ", ".join(approvers.mapped("name")))
            self.env["yapie.log"].add("approval", _("%(d)s sent for approval to %(a)s", d=rec.display_name, a=", ".join(approvers.mapped("name"))), user=by, record=rec)
            out |= req
        return out

    # ---------- the decision ----------
    @api.model
    def handle_decision(self, data):
        api_ = self.env["yapie.api"].sudo()
        card = self.env["yapie.approval.card"].sudo().search([("yapie_id", "=", int(data.get("id") or 0))], limit=1)
        if not card:
            return False
        req = card.request_id
        status = data.get("status")
        who = data.get("decided_by") or {}
        user = self.env["res.users"]._yapie_by_uid(who.get("id"))

        def answer(ok, note):
            try:
                api_.call("/approvals/%s/applied" % card.yapie_id, {"ok": ok, "note": note})
            except UserError as e:
                _logger.warning("Yapie approval %s: could not report back: %s", card.yapie_id, e)

        if req.state != "pending":
            card.state = "closed"
            answer(False, _("Already %s in Odoo") % dict(req._fields["state"].selection).get(req.state))
            return False
        # the person who decided must be a linked, authorised approver of this request, now
        if not user or not user._yapie_authorized() or user not in req.approver_ids or (req.rule_id and user not in req.rule_id.approvers()):
            card.state = "closed"
            self.env["yapie.log"].add("denied", _("Approval of %(d)s by %(n)s refused: not an authorised approver in Odoo", d=req.name, n=who.get("name") or "?"),
                                      yapie_name=who.get("name"), state="error")
            answer(False, _("Not an authorised approver in Odoo — nothing changed"))
            return False
        rec = self.env[req.res_model].sudo().browse(req.res_id).exists()
        rule = req.rule_id
        # a document that follows an Odoo workflow and no longer waits was decided inside Odoo: don't act twice
        if rule.workflow_key and (not rec or not rule.matches(rec)):
            card.state = "closed"
            req._yapie_close(_("Already decided in Odoo"))
            answer(False, _("Already decided in Odoo — nothing changed"))
            return False
        # every approver must approve: record this approval and wait for the others
        if status == "approved" and rule.approval_mode == "all":
            req.approved_user_ids = [(4, user.id)]
            waiting = req.approver_ids.filtered(lambda u: u._yapie_authorized()) - req.approved_user_ids
            if waiting:
                card.state = "decided"
                if rec and hasattr(rec, "message_post"):
                    rec.sudo().message_post(body=_("✅ Approved by %(n)s on Yapie — still waiting for %(w)s", n=user.name, w=", ".join(waiting.mapped("name"))),
                                            author_id=user.partner_id.id)
                self.env["yapie.log"].add("approval", _("%(d)s approved by %(n)s, waiting for %(w)s", d=req.name, n=user.name, w=", ".join(waiting.mapped("name"))),
                                          user=user, record=rec or None)
                answer(True, _("Your approval is recorded — waiting for %s") % ", ".join(waiting.mapped("name")))
                return True
        method = rule.approve_method if status == "approved" else rule.reject_method if status == "rejected" else False
        ok, note = True, ""
        if rec and method:
            try:
                with self.env.cr.savepoint():
                    if status == "rejected" and rule.reason_field and rule.reason_field in rec._fields:
                        rec.sudo().write({rule.reason_field: data.get("comment") or _("Rejected on Yapie by %s") % user.name})
                    getattr(rec.sudo(False).with_user(user), method)()
                note = _("done")
            except Exception as e:  # noqa: BLE001  the decision stays recorded; the document just didn't change
                ok, note = False, str(e)[:180]
        req.write({"state": status if status in ("approved", "rejected") else "pending", "decided_user_id": user.id, "decided_at": fields.Datetime.now(),
                   "comment": data.get("comment") or False, "via": data.get("via"), "applied": "ok" if (ok and method) else ("error" if not ok else "none"),
                   "applied_note": note})
        card.state = "decided"
        if rec and hasattr(rec, "message_post"):
            icon = "✅" if status == "approved" else "❌"
            text = _("%(i)s %(s)s by %(n)s on Yapie%(v)s%(c)s", i=icon, s=_("Approved") if status == "approved" else _("Rejected"), n=user.name,
                     v=_(" (by reply)") if data.get("via") == "reply" else "", c=(": “%s”" % data["comment"]) if data.get("comment") else "")
            if not ok:
                text += _(" — could not run %(m)s: %(e)s", m=method, e=note)
            rec.sudo().message_post(body=text, author_id=user.partner_id.id)
        answer(ok, note if not ok else (rec.display_name if rec else ""))
        # withdraw the other approvers' cards
        for other in req.card_ids.filtered(lambda c: c.id != card.id and c.state == "open"):
            try:
                api_.call("/approvals/%s/cancel" % other.yapie_id, {})
            except UserError:
                pass
            other.state = "closed"
        self.env["yapie.log"].add("approval", _("%(d)s %(s)s by %(n)s", d=req.name, s=status, n=user.name), user=user, record=rec or None,
                                  state="ok" if ok else "error")
        if req.rule_id.notify_requester and req.requested_by and req.requested_by != user and req.requested_by._yapie_authorized():
            try:
                api_.send_text(api_.target_of(req.requested_by), _("%(i)s %(d)s was %(s)s by %(n)s%(c)s", i="✅" if status == "approved" else "❌", d=req.name,
                                                                    s=_("approved") if status == "approved" else _("rejected"), n=user.name,
                                                                    c=(" — “%s”" % data["comment"]) if data.get("comment") else ""))
            except UserError:
                pass
        return True

    def action_withdraw(self):
        api_ = self.env["yapie.api"].sudo()
        for req in self.filtered(lambda r: r.state == "pending"):
            if req.requested_by != self.env.user and not self.env.user.has_group("yapie.group_yapie_manager"):
                raise AccessError(_("Only the person who asked (or a Yapie administrator) can withdraw it."))
            for c in req.card_ids.filtered(lambda c: c.state == "open"):
                try:
                    api_.call("/approvals/%s/cancel" % c.yapie_id, {})
                except UserError:
                    pass
                c.state = "closed"
            req.sudo().state = "cancelled"
        return True

    def action_open_document(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "res_model": self.res_model, "res_id": self.res_id, "view_mode": "form"}


class YapieApprovalCard(models.Model):
    """The card(s) in Yapie for one request: one in a group, or one per approver."""
    _name = "yapie.approval.card"
    _description = "Yapie approval card"

    request_id = fields.Many2one("yapie.approval.request", required=True, ondelete="cascade", index=True)
    yapie_id = fields.Integer(required=True, index=True)
    user_id = fields.Many2one("res.users", "Approver")
    chat_id = fields.Many2one("yapie.chat", "Group")
    state = fields.Selection([("open", "Waiting"), ("decided", "Decided"), ("closed", "Closed")], default="open", required=True)

    _yapie_unique = models.Constraint("UNIQUE(yapie_id)", "This Yapie approval is already linked.")
