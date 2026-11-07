import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class YapieApi(models.AbstractModel):
    """Client for the Yapie bot API, and the inbox: what arrives from Yapie (messages to the bot, approval
    decisions, attendance) is dispatched from here, whether it came by webhook or by polling."""
    _name = "yapie.api"
    _description = "Yapie API"

    # ---------- configuration ----------
    @api.model
    def _param(self, key, default=""):
        return self.env["ir.config_parameter"].sudo().get_param(key) or default

    @api.model
    def _conf(self):
        return self._param("yapie.base_url", "https://yapie.app").rstrip("/"), self._param("yapie.token")

    @api.model
    def is_configured(self):
        return bool(self._conf()[1])

    # ---------- HTTP ----------
    @api.model
    def call(self, path, body=None, method=None, query=None, raw=None, content_type=None, timeout=20):
        base, token = self._conf()
        if not token:
            raise UserError(_("Add the Yapie bot token in Settings › Yapie first."))
        url = base + "/api/v1" + path
        if query:
            url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v not in (None, False, "")})
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(url, data=data, method=method or ("POST" if data is not None else "GET"))
        req.add_header("Authorization", "Bearer " + token)
        if data is not None:
            req.add_header("Content-Type", content_type or "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read()).get("error")
            except Exception:
                msg = None
            raise UserError(_("Yapie: %s") % (msg or e.code))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise UserError(_("Yapie can't be reached (%s).") % getattr(e, "reason", e))

    # ---------- sending ----------
    @api.model
    def target_of(self, user):
        """Where a linked user is reached: their chat with the bot (once known), else what they linked with."""
        user = user.sudo()
        if user.yapie_chat_id:
            return {"chat_id": user.yapie_chat_id}
        if user.yapie_target:
            return {"to": user.yapie_target}
        raise UserError(_("%s hasn't linked a Yapie account.") % user.name)

    @api.model
    def send_text(self, target, text, buttons=None):
        body = dict(target, text=text[:4000])
        if buttons:
            body["buttons"] = buttons
        return self.call("/messages", body)

    @api.model
    def send_later(self, target, text):
        """Send after the current transaction commits (so saving a document never waits for Yapie, and nothing is
        sent if the save is rolled back)."""
        base, token = self._conf()
        if not token:
            return
        body = json.dumps(dict(target, text=text[:4000])).encode()

        def go():
            req = urllib.request.Request(base + "/api/v1/messages", data=body, method="POST")
            req.add_header("Authorization", "Bearer " + token)
            req.add_header("Content-Type", "application/json")
            try:
                urllib.request.urlopen(req, timeout=15).read()
            except Exception as e:  # noqa: BLE001
                _logger.info("Yapie: message not sent: %s", e)
        self.env.cr.postcommit.add(go)

    @api.model
    def send_file(self, target, name, mime, content, caption=""):
        q = dict(target, name=name, caption=caption[:1000])
        return self.call("/files", query=q, raw=content, content_type=mime, timeout=60)

    @api.model
    def chat_members(self, chat_id):
        return self.call("/chats/%s" % int(chat_id)).get("members") or []

    # ---------- receiving ----------
    @api.model
    def dispatch(self, event, data):
        """One thing from Yapie. Never raises: a bad update must not block the ones after it."""
        try:
            with self.env.cr.savepoint():
                self._dispatch(event, data or {})
        except Exception as e:  # noqa: BLE001
            _logger.exception("Yapie: could not handle %s", event)
            self.env["yapie.log"].sudo().add("error", _("Could not handle %(event)s: %(error)s", event=event, error=str(e)[:300]), state="error")

    @api.model
    def _dispatch(self, event, data):
        if event == "message":
            self.env["yapie.bot"].sudo().handle_message(data)
        elif event == "approval.decided":
            self.env["yapie.approval.request"].sudo().handle_decision(data)

    @api.model
    def poll(self, seconds=50):
        """Collect updates (for an Odoo without a public address). Runs from a cron every minute and keeps
        listening for up to `seconds`, so replies come within a second or two."""
        if not self.is_configured() or self._param("yapie.mode", "polling") != "polling":
            return 0
        ICP = self.env["ir.config_parameter"].sudo()
        end = time.time() + seconds
        done = 0
        while True:
            after = int(ICP.get_param("yapie.last_update") or 0)
            left = int(end - time.time())
            try:
                ups = self.call("/updates", query={"after": after, "timeout": max(0, min(20, left))}, timeout=30).get("updates") or []
            except UserError as e:
                _logger.warning("Yapie polling: %s", e)
                return done
            for u in ups:
                self.dispatch(u.get("event"), u.get("data"))
                ICP.set_param("yapie.last_update", str(u.get("update_id")))
                done += 1
                self.env.cr.commit()  # each update is handled once, even if a later one fails
            if time.time() >= end or (not ups and left <= 0):
                return done
            if not ups and seconds == 0:
                return done

    @api.model
    def poll_once(self):
        """Settings button / tests: collect what's waiting now, without waiting for more."""
        if not self.env.user.has_group("yapie.group_yapie_manager"):
            raise UserError(_("Only Yapie administrators can do this."))
        return self.sudo().poll(seconds=0)
