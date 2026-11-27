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
        # remember the person's chat with the bot and their current username (on their own account: the user's
        # main link, or the additional account they wrote from)
        account = self.env["res.users"]._yapie_link_by_uid(sender["id"]) or user.sudo()
        vals = {}
        if direct and chat.get("id") and account.yapie_chat_id != chat["id"]:
            vals["yapie_chat_id"] = chat["id"]
        if sender.get("username") and account.yapie_username != sender["username"]:
            vals["yapie_username"] = sender["username"]
        if vals:
            account.sudo().write(vals)
        # the trail and the person's own role follow the Yapie account that wrote (main or additional)
        link = account if account._name == "yapie.user.link" else self.env["yapie.user.link"]
        self = self.with_context(yapie_account=self.env["res.users"]._yapie_account_info(sender["id"]), yapie_link_id=link.id)
        if direct:
            me = {"chat_id": chat["id"]}
        else:
            me = account.target() if account._name == "yapie.user.link" else api_.target_of(user)
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
            self.env["yapie.log"].add("command", text[:200], user=user)
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
        # creating a record: every message answers the current question until it is created or cancelled
        if sess and sess.get("create"):
            return self._create_step(user, sess, text, me)
        if low in ("create", "new", "add", "create new"):
            return self._create_menu(user, me)
        m = re.match(r"^(create|new|add)\s+(.+)$", low)
        if m and self._create_start(user, m.group(2), me):
            return
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
        if self.env["yapie.create.type"].allowed_list(user):
            lines.append(_("“create” shows what you can add (accounts, customers, …)."))
        buttons = [[{"text": t.name, "data": t.keyword_list()[0]} for t in types.filtered(lambda x: x.needs_partner != "required")[:3]]]
        return api_.send_text(me, "\n".join(lines), buttons=buttons if buttons[0] else None)

    # ---------- creating records ----------
    def _create_menu(self, user, me):
        api_ = self.env["yapie.api"].sudo()
        types = self.env["yapie.create.type"].allowed_list(user)
        if not types:
            return api_.send_text(me, _("You can't create anything from Yapie yet. Ask your administrator."))
        lines = [_("You can create:")] + ["• %s — “create %s”" % (t.name, t.keyword_list()[0]) for t in types]
        lines.append(_("I'll ask for each detail; send “cancel” any time to stop."))
        return api_.send_text(me, "\n".join(lines))

    def _create_start(self, user, words, me):
        """'create <keyword>': True when the words name a create type (allowed or not)."""
        api_ = self.env["yapie.api"].sudo()
        best, kw_len = None, 0
        for t in self.env["yapie.create.type"].sudo().search([]):
            for k in t.keyword_list():
                if (words == k or words.startswith(k + " ")) and len(k) > kw_len:
                    best, kw_len = t, len(k)
        if not best:
            return False
        if not best.allowed_for(user):
            self.env["yapie.log"].add("denied", _("%(u)s tried to create %(t)s (not allowed)", u=user.name, t=best.name), user=user, state="error")
            api_.send_text(me, _("You may not create %s. Send “create” to see what you can create.") % best.name)
            return True
        if not best.field_line_ids:
            api_.send_text(me, _("%s isn't set up yet (no fields). Ask your administrator.") % best.name)
            return True
        sess = {"create": best.id, "i": 0, "vals": {}, "shown": []}
        self._session(user, sess)
        api_.send_text(me, _("New %(t)s — %(n)d question(s). Send “cancel” to stop.\n\n%(q)s",
                             t=best.name, n=len(best.field_line_ids), q=best.field_line_ids[0].question()))
        return True

    def _create_step(self, user, sess, text, me):
        api_ = self.env["yapie.api"].sudo()
        ctype = self.env["yapie.create.type"].sudo().browse(sess["create"]).exists()
        low = text.strip().lower()
        if not ctype or low in ("cancel", "stop", "exit", "quit"):
            self._session(user, clear=True)
            return api_.send_text(me, _("Cancelled — nothing was created."))
        if not ctype.allowed_for(user):  # rights may have changed mid-way
            self._session(user, clear=True)
            return api_.send_text(me, _("You may no longer create %s.") % ctype.name)
        lines = ctype.field_line_ids
        if sess.get("confirm"):
            if low in ("yes", "y", "ok", "confirm", "create", "haan"):
                self._session(user, clear=True)
                return self._create_do(user, ctype, sess, me)
            return api_.send_text(me, _("Send “yes” to create it, or “cancel”."))
        line = lines[sess["i"]]
        value = display = None
        skipped = False
        if sess.get("choices") and low.isdigit() and 1 <= int(low) <= len(sess["choices"]):
            value, display = sess["choices"][int(low) - 1]
        elif low == "skip" and not line.required:
            skipped, display = True, "—"
        else:
            try:
                value, display, choices = line.parse(text, user)
            except UserError as e:
                return api_.send_text(me, "⚠️ %s\n\n%s" % (e.args[0], line.question()))
            if choices:
                sess["choices"] = choices
                self._session(user, sess)
                rows = [_("Which one?")] + ["%d. %s" % (i + 1, n) for i, (_id, n) in enumerate(choices)] + [_("Reply with the number.")]
                return api_.send_text(me, "\n".join(rows))
        sess.pop("choices", None)
        if not skipped:
            sess["vals"][line.field_id.name] = value
        sess["shown"].append([line.prompt or line.field_id.field_description, display])
        sess["i"] += 1
        if sess["i"] < len(lines):
            self._session(user, sess)
            return api_.send_text(me, lines[sess["i"]].question())
        sess["confirm"] = True
        self._session(user, sess)
        summary = "\n".join("• %s: %s" % (k, v) for k, v in sess["shown"])
        return api_.send_text(me, _("Create this %(t)s?\n%(s)s\n\nSend “yes” to create, or “cancel”.", t=ctype.name, s=summary))

    def _create_do(self, user, ctype, sess, me):
        from .yapie_approval import doc_link
        api_ = self.env["yapie.api"].sudo()
        vals = dict(ctype._fixed())
        vals.update(sess["vals"])
        try:
            with self.env.cr.savepoint():
                # as the person's Odoo user: Odoo's own access rights and checks apply
                rec = self.env[ctype.model].with_user(user).with_company(user.company_id).create(vals)
        except (UserError, AccessError, ValidationError) as e:
            self.env["yapie.log"].add("create", _("%(t)s not created: %(e)s", t=ctype.name, e=str(e)[:200]), user=user, state="error")
            return api_.send_text(me, _("⚠️ Not created: %s") % (e.args[0] if e.args else e))
        if hasattr(rec, "message_post"):
            who = self.env.context.get("yapie_account", {}).get("label") or user.name
            rec.sudo().message_post(body=_("Created from Yapie by %(u)s (%(w)s)", u=user.name, w=who), author_id=user.partner_id.id)
        self.env["yapie.log"].add("create", _("%(t)s created: %(d)s", t=ctype.name, d=rec.display_name), user=user, record=rec)
        note = ""
        if ctype.send_for_approval:
            Req = self.env["yapie.approval.request"].sudo()
            for rule in self.env["yapie.approval.rule"].sudo().search([("model", "=", rec._name)]):
                if not rule.matches(rec) or Req.search_count([("res_model", "=", rec._name), ("res_id", "=", rec.id), ("state", "=", "pending")]):
                    continue  # a rule asking automatically has already sent it
                if rule.approvers() and rule.can_request(user, rec):
                    try:
                        with self.env.cr.savepoint():
                            Req.request(rec, rule, by=user)
                    except (UserError, AccessError) as e:
                        note += "\n" + _("Could not send for approval: %s") % (e.args[0] if e.args else e)
            pending = Req.search([("res_model", "=", rec._name), ("res_id", "=", rec.id), ("state", "=", "pending")])
            if pending:
                note += "\n" + _("Sent for approval to %s.") % ", ".join(pending.mapped("approver_ids.name"))
        return api_.send_text(me, _("✅ Created %(t)s: %(d)s\n%(l)s%(n)s", t=ctype.name, d=rec.display_name, l=doc_link(rec), n=note))

    def _pending(self, user, me):
        reqs = self.env["yapie.approval.request"].sudo().search([("state", "=", "pending"), ("approver_ids", "in", user.id)], limit=20)
        link = self.env["yapie.user.link"].sudo().browse(self.env.context.get("yapie_link_id") or [])
        if link:
            reqs = reqs.filtered(lambda r: link.allows_approval(r.rule_id))
        if not reqs:
            return self.env["yapie.api"].sudo().send_text(me, _("Nothing is waiting for your approval. 🎉"))
        lines = [_("Waiting for you (%s):") % len(reqs)] + ["• %s — %s" % (r.name, fmt_date(r.create_date.date())) for r in reqs]
        lines.append(_("Approve or reject on each card above (or reply “approve” / “reject - reason” to it)."))
        return self.env["yapie.api"].sudo().send_text(me, "\n".join(lines))
