from odoo import _, fields, models


class YapieApprovalWizard(models.TransientModel):
    _name = "yapie.approval.wizard"
    _description = "Request approval on Yapie"

    res_model = fields.Char(required=True)
    res_ids = fields.Char(required=True)
    rule_id = fields.Many2one("yapie.approval.rule", required=True, domain="[('model', '=', res_model)]")
    note = fields.Char("Note for the approver")

    def action_send(self):
        self.ensure_one()
        records = self.env[self.res_model].browse([int(x) for x in self.res_ids.split(",") if x])
        records.check_access("read")
        reqs = self.env["yapie.approval.request"].sudo().request(records, self.rule_id.sudo(), note=self.note, by=self.env.user)
        return {"type": "ir.actions.client", "tag": "display_notification",
                "params": {"title": _("Sent to Yapie"), "message": _("%s approval request(s) sent.") % len(reqs), "type": "success",
                           "next": {"type": "ir.actions.act_window_close"}}}
