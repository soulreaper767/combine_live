import hashlib
import hmac
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class YapieWebhook(http.Controller):
    """Yapie calls this (webhook mode). Only requests signed with this database's secret are accepted."""

    @http.route("/yapie/webhook", type="http", auth="public", methods=["POST"], csrf=False, save_session=False)
    def webhook(self, **_kw):
        body = request.httprequest.get_data() or b""
        env = request.env(su=True)
        secret = env["ir.config_parameter"].get_param("yapie.webhook_secret") or ""
        sent = request.httprequest.headers.get("X-Yapie-Signature", "")
        good = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not secret or not hmac.compare_digest(sent, good):
            return request.make_response("bad signature", status=401)
        try:
            payload = json.loads(body)
        except ValueError:
            return request.make_response("bad json", status=400)
        env["yapie.api"].dispatch(payload.get("event"), payload.get("data") or {})
        return request.make_response("ok")
