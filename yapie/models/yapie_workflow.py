"""Odoo's own approval workflows, so Yapie approvals follow them exactly.

Each workflow tells Yapie: which documents are waiting (a domain), who may decide (Odoo groups / users - read
live, never copied), whether any one of them or every one must approve, and which of the document's own
buttons approve / reject it. `yapie.approval.rule._yapie_sync_workflows()` turns them into rules that can't
be edited by hand; other modules add their workflows by extending `_yapie_workflows()`.
"""
from odoo import _, api, models


class YapieWorkflow(models.AbstractModel):
    _name = "yapie.workflow"
    _description = "Odoo approval workflows followed by Yapie"

    @api.model
    def _yapie_workflows(self):
        """List of dicts:
        key        unique id of the workflow
        name       shown as the rule name
        model      document model
        domain     documents waiting for this approval (list domain)
        groups     xml ids of the Odoo groups whose members approve
        user_ids   ids of specific approvers (optional)
        mode       'any' (one of them decides) or 'all' (every one of them must approve)
        approve    the document's own approve button (runs as the approver)
        reject     the document's own reject button (optional)
        reason_field  field the rejection reason is written to before `reject` runs (optional)
        """
        out = []
        if "purchase.order" in self.env:
            companies = self.env["res.company"].sudo().search([])
            if any(getattr(c, "po_double_validation", "one_step") == "two_step" for c in companies):
                out.append({
                    "key": "purchase.order.two_step", "name": _("Purchase Order approval (Odoo: Purchase › Settings › Order approval)"),
                    "model": "purchase.order", "domain": [("state", "=", "to approve")],
                    "groups": ["purchase.group_purchase_manager"], "mode": "any",
                    "approve": "button_approve", "reject": "button_cancel",
                })
        return out
