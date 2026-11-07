import json
import logging
import re
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from ..tools import clean_words, fmt_date, parse_period

_logger = logging.getLogger(__name__)

GREETINGS = {"hi", "hello", "hey", "menu", "help", "start", "/start", "/help", "salam", "aoa", "assalam o alaikum", "?"}
PRIVATE_REPLY = ("This is a private company assistant. If you work here, ask your Odoo administrator to link your Yapie "
                 "account (Odoo › Preferences › Link Yapie).")


class YapieBotSession(models.Model):
    """A short-lived question the bot asked someone (e.g. 'which Acme did you mean?')."""
    _name = "yapie.bot.session"
    _description = "Yapie bot question"

    user_id = fields.Many2one("res.users", required=True, ondelete="cascade", index=True)
    data = fields.Text()
    expires = fields.Datetime()

    @api.autovacuum
    def _gc(self):
        self.search([("expires", "<", fields.Datetime.now())]).unlink()


class YapieBot(models.AbstractModel):
    """Messages to the bot. Only linked, authorised people get answers; everyone else gets one short
    'private assistant' reply a day and nothing about the company."""
    _name = "yapie.bot"
    _description = "Yapie bot"

    # ---------- entry ----------
    @api.model
    def handle_message(self, data):
        sender = data.get("from") or {}
        chat = data.get("chat") or {}
        text = (data.get("text") or "").strip()
        if sender.get("is_bot") or not sender.get("id"):
            return
        user = self.env["res.users"]._yapie_by_uid(sender["id"])
        name = sender.get("display_name") or sender.get("username") or "?"
        authorized = bool(user) and user._yapie_authorized()
        direct = chat.get("kind") == "direct"
        api_ = self.env["yapie.api"].sudo()
        if not authorized:
            self._refuse(sender, chat, direct, name, user)
            return
        # remember the person's chat with the bot and their current username
        vals = {}
        if direct and chat.get("id") and user.yapie_chat_id != chat["id"]:
            vals["yapie_chat_id"] = chat["id"]
        if sender.get("username") and user.yapie_username != sender["username"]:
            vals["yapie_username"] = sender["username"]
        if vals:
            user.sudo().write(vals)
        me = {"chat_id": chat["id"]} if direct else api_.target_of(user)
        if not direct:
            # in a group the bot only answers "/" commands, and always privately
            if not text.startswith("/"):
                return
            if text.lower().startswith("/groupid"):
                api_.send_text(me, _("This Yapie group's ID is %s. Register it in Odoo › Yapie › Groups.") % chat.get("id"))
                return
            text = text[1:]
        if data.get("kind") not in (None, "text"):
            return
        # replies to a card and "approve" / "reject …" are decisions: Yapie handles them (they come back as approval.decided)
        if data.get("reply_to") or re.match(r"^(approve|approved|reject|rejected)\b", text.strip().lower()):
            return
        try:
            self.with_user(user).with_company(user.company_id)._answer(user, text, me)
        except (UserError, AccessError) as e:
            api_.send_text(me, "⚠️ " + (e.args[0] if e.args else str(e)))
            self.env["yapie.log"].add("command", "%s → %s" % (text[:120], str(e)[:200]), user=user, state="error")
        except Exception as e:  # noqa: BLE001
            _logger.exception("Yapie bot")
            api_.send_text(me, _("⚠️ Sorry, that didn't work. Please try again or contact your administrator."))
            self.env["yapie.log"].add("error", "%s → %s" % (text[:120], str(e)[:200]), user=user, state="error")

    def _refuse(self, sender, chat, direct, name, user):
        Log = self.env["yapie.log"].sudo()
        why = _("linked but not allowed to use Yapie") if user else _("not linked")
        if not direct:
            return  # never answer strangers in groups
        recent = Log.search_count([("kind", "=", "denied"), ("yapie_name", "=", name), ("rule_ref", "=", "uid:%s" % sender["id"]),
                                   ("create_date", ">", fields.Datetime.now() - timedelta(days=1))])
        Log.create({"kind": "denied", "yapie_name": name, "summary": _("Message from %(n)s refused (%(w)s)", n=name, w=why),
                    "state": "error", "rule_ref": "uid:%s" % sender["id"], "user_id": user.id if user else False})
        if not recent:
            try:
                self.env["yapie.api"].sudo().send_text({"chat_id": chat["id"]}, PRIVATE_REPLY)
            except UserError as e:  # the refusal stays logged even if the reply can't be sent
                _logger.info("Yapie: private-assistant reply not sent: %s", e)

    # ---------- conversation ----------
    def _session(self, user, data=None, clear=False):
        S = self.env["yapie.bot.session"].sudo()
        s = S.search([("user_id", "=", user.id)], limit=1)
        if clear:
            s.unlink()
            return None
        if data is not None:
            vals = {"user_id": user.id, "data": json.dumps(data, default=str), "expires": fields.Datetime.now() + timedelta(minutes=15)}
            s.write(vals) if s else S.create(vals)
            return data
        if s and s.expires and s.expires > fields.Datetime.now():
            return json.loads(s.data or "{}")
        return None

    def _answer(self, user, text, me):
        api_ = self.env["yapie.api"].sudo()
        low = re.sub(r"\s+", " ", text.lower()).strip(" .!")
        types = self.env["yapie.report.type"].allowed_list(user)
        # a number answers the bot's last question
        sess = self._session(user)
        if sess and low.isdigit() and sess.get("choices"):
            i = int(low) - 1
            if 0 <= i < len(sess["choices"]):
                self._session(user, clear=True)
                params = sess["params"]
                params["date_from"] = fields.Date.to_date(params.get("date_from") or None)
                params["date_to"] = fields.Date.to_date(params.get("date_to") or None)
                params["partner_id"] = sess["choices"][i][0]
                return self._send_report(user, self.env["yapie.report.type"].browse(sess["type_id"]), params, sess["fmt"], me)
        if low in GREETINGS or not low:
            return self._menu(user, types, me)
        if low in ("approvals", "pending", "my approvals", "waiting"):
            return self._pending(user, me)
        if low in ("me", "whoami", "who am i", "status"):
            return api_.send_text(me, _("You're linked as %(u)s (%(c)s). You can get: %(r)s.", u=user.name, c=user.company_id.name,
                                        r=", ".join(types.mapped("name")) or _("no reports yet")))
        # which report? the longest keyword the message starts with
        best, kw_len = None, 0
        all_types = self.env["yapie.report.type"].sudo().search([])
        for t in all_types:
            for k in t.keyword_list():
                if (low == k or low.startswith(k + " ")) and len(k) > kw_len:
                    best, kw_len = t, len(k)
        if not best:
            return api_.send_text(me, _("I didn't get that. Send “menu” to see what I can send you."))
        if best not in types:
            self.env["yapie.log"].add("denied", _("%(u)s asked for %(r)s (not allowed)", u=user.name, r=best.name), user=user, state="error")
            return api_.send_text(me, _("You don't have access to %s. Ask your administrator if you need it.") % best.name)
        rest = text[kw_len:]
        fmt = "xlsx" if re.search(r"\b(excel|xlsx|xls|sheet)\b", rest.lower()) else "pdf"
        today = fields.Date.context_today(user.with_context(tz=user.tz))
        f, t, _key, rest = parse_period(rest, today, self.env["yapie.report"].fy_start(self.env, today))
        words = clean_words(rest)
        params = {"date_from": f, "date_to": t, "text": words if best.code == "stock_onhand" else ""}
        if best.needs_partner != "no" and words:
            partners = self._find_partner(words)
            if not partners:
                return api_.send_text(me, _("I couldn't find “%s”. Check the name, or send part of it.") % words)
            if len(partners) > 1:
                choices = [(p.id, p.display_name) for p in partners[:9]]
                self._session(user, {"choices": choices, "type_id": best.id, "params": params, "fmt": fmt})
                lines = [_("Which one?")] + ["%d. %s" % (i + 1, n) for i, (_id, n) in enumerate(choices)] + [_("Reply with the number.")]
                return api_.send_text(me, "\n".join(lines), buttons=[[{"text": str(i + 1), "data": str(i + 1)} for i in range(min(len(choices), 5))]])
            params["partner_id"] = partners.id
        elif best.needs_partner == "required":
            ex = best.example or "%s Acme this year" % best.keyword_list()[0]
            return api_.send_text(me, _("Which customer or vendor? e.g. “%s”") % ex)
        return self._send_report(user, best, params, fmt, me)

    def _find_partner(self, words):
        """Partners this person can see (their record rules apply), best matches first."""
        P = self.env["res.partner"]
        exact = P.search([("name", "=ilike", words), ("parent_id", "=", False)], limit=2)
        if len(exact) == 1:
            return exact
        found = P.search([("name", "ilike", words), ("parent_id", "=", False)], limit=9)
        if not found:
            found = P.search([("display_name", "ilike", words)], limit=9).mapped("commercial_partner_id")
        return found

    def _send_report(self, user, rtype, params, fmt, me):
        api_ = self.env["yapie.api"].sudo()
        name, mime, content, caption = self.env["yapie.report"].generate(rtype, user, params, fmt)
        api_.send_file(me, name, mime, content, caption)
        self.env["yapie.log"].add("report", "%s · %s" % (rtype.name, caption.split("\n")[0][:200]), user=user)

    def _menu(self, user, types, me):
        api_ = self.env["yapie.api"].sudo()
        if not types:
            return api_.send_text(me, _("Hi %s! You're linked, but no reports are open to you yet. Ask your administrator.") % user.name.split(" ")[0])
        lines = [_("Hi %(n)s 👋 — %(c)s. Ask me for:", n=user.name.split(" ")[0], c=user.company_id.name)]
        for t in types:
            lines.append("• %s — “%s”" % (t.name, t.example or t.keyword_list()[0]))
        lines += ["", _("Add a period (“last month”, “1/7/2026 30/9/2026”) and “excel” for a spreadsheet."), _("“approvals” lists what's waiting for you.")]
        buttons = [[{"text": t.name, "data": t.keyword_list()[0]} for t in types.filtered(lambda x: x.needs_partner != "required")[:3]]]
        return api_.send_text(me, "\n".join(lines), buttons=buttons if buttons[0] else None)

    def _pending(self, user, me):
        reqs = self.env["yapie.approval.request"].sudo().search([("state", "=", "pending"), ("approver_ids", "in", user.id)], limit=20)
        if not reqs:
            return self.env["yapie.api"].sudo().send_text(me, _("Nothing is waiting for your approval. 🎉"))
        lines = [_("Waiting for you (%s):") % len(reqs)] + ["• %s — %s" % (r.name, fmt_date(r.create_date.date())) for r in reqs]
        lines.append(_("Approve or reject on each card above (or reply “approve” / “reject - reason” to it)."))
        return self.env["yapie.api"].sudo().send_text(me, "\n".join(lines))
