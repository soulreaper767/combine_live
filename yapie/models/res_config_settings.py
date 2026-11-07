from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    yapie_base_url = fields.Char("Yapie server", config_parameter="yapie.base_url", default="https://yapie.app")
    yapie_token = fields.Char("Bot token", config_parameter="yapie.token")
    yapie_mode = fields.Selection([("polling", "Odoo collects messages (works anywhere, even without a public address)"),
                                   ("webhook", "Yapie sends them to Odoo (needs a public https address)")],
                                  "Receiving", config_parameter="yapie.mode", default="polling")
    yapie_webhook_url = fields.Char("Webhook address", compute="_compute_yapie_webhook_url")
    yapie_bot_name = fields.Char("Bot", config_parameter="yapie.bot_name", readonly=True)

    def _compute_yapie_webhook_url(self):
        base = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "").rstrip("/")
        for s in self:
            s.yapie_webhook_url = base + "/yapie/webhook"

    def set_values(self):
        super().set_values()
        cron = self.env.ref("yapie.ir_cron_yapie_poll", raise_if_not_found=False)
        if cron:
            cron.sudo().active = bool(self.yapie_token) and (self.yapie_mode or "polling") == "polling"

    def action_yapie_connect(self):
        """Check the token, and point Yapie at this Odoo (webhook) or stop the webhook (polling)."""
        self.ensure_one()
        self.set_values()
        api_ = self.env["yapie.api"]
        me = api_.call("/me")
        bot = (me.get("bot") or {})
        ICP = self.env["ir.config_parameter"].sudo()
        ICP.set_param("yapie.bot_name", "%s (@%s)" % (bot.get("display_name", ""), bot.get("username", "")))
        if (self.yapie_mode or "polling") == "webhook":
            if not self.yapie_webhook_url.startswith("https://"):
                raise UserError(_("Yapie can only call an https address. Use “Odoo collects messages” instead, or set web.base.url to https."))
            r = api_.call("/webhook", {"url": self.yapie_webhook_url})
            ICP.set_param("yapie.webhook_secret", r.get("secret") or "")
            msg = _("Connected to %(b)s. Yapie sends messages to %(u)s.", b=bot.get("display_name"), u=r.get("webhook"))
        else:
            api_.call("/webhook", {"url": ""})
            ICP.set_param("yapie.webhook_secret", "")
            msg = _("Connected to %s. Odoo collects messages every few seconds.") % bot.get("display_name")
        return {"type": "ir.actions.client", "tag": "display_notification",
                "params": {"title": _("Yapie connected"), "message": msg, "type": "success", "next": {"type": "ir.actions.client", "tag": "soft_reload"}}}

    def action_yapie_poll_now(self):
        n = self.env["yapie.api"].poll_once()
        return {"type": "ir.actions.client", "tag": "display_notification",
                "params": {"title": _("Yapie"), "message": _("%s update(s) handled.") % n, "type": "info"}}
