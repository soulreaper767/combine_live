import io
import logging
from collections import defaultdict
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..tools import fmt_date, fmt_money, period_range

_logger = logging.getLogger(__name__)
MAX_ROWS = 5000


class YapieReport(models.AbstractModel):
    """Builds the reports people get in Yapie. Every builder runs in the requesting person's environment
    (their access rights, record rules and company), never as superuser."""
    _name = "yapie.report"
    _description = "Yapie report builder"

    # ---------- entry point ----------
    @api.model
    def generate(self, rtype, user, params, fmt="pdf"):
        """Returns (filename, mime, content, caption). `params`: partner_id, date_from, date_to, text."""
        if not rtype.allowed_for(user):
            raise UserError(_("You don't have access to %s.") % rtype.name)
        env = self.with_user(user).with_company(user.company_id).with_context(lang=user.lang, tz=user.tz).env
        builder = getattr(self, "_build_" + rtype.code, None)
        if not builder:
            raise UserError(_("%s isn't available here.") % rtype.name)
        data = builder(env, dict(params))
        data.setdefault("title", rtype.name)
        data["company"] = env.company.name
        data["generated"] = _("Generated %(when)s for %(who)s", when=fields.Datetime.context_timestamp(env.user, fields.Datetime.now()).strftime("%d %b %Y %H:%M"), who=user.name)
        base = "".join(c if c.isalnum() or c in " -_" else "_" for c in "%s %s" % (data["title"], data.get("file_hint") or "")).strip()
        if fmt == "xlsx":
            return base + ".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", self._xlsx(data), data.get("caption") or data["title"]
        return base + ".pdf", "application/pdf", self._pdf(data), data.get("caption") or data["title"]

    @api.model
    def fy_start(self, env, today):
        company = env.company
        if hasattr(company, "compute_fiscalyear_dates"):
            try:
                return company.compute_fiscalyear_dates(today)["date_from"]
            except Exception:  # noqa: BLE001
                return None
        return None

    @api.model
    def resolve_period(self, env, rtype, params):
        today = fields.Date.context_today(env.user)
        f, t = params.get("date_from"), params.get("date_to")
        if not f and not t:
            f, t = period_range(rtype.default_period, today, self.fy_start(env, today))
        return f, t or today

    # ---------- shared ----------
    def _cur(self, env):
        return env.company.currency_id.symbol or env.company.currency_id.name

    def _period_text(self, f, t):
        return _("as of %s") % fmt_date(t) if not f else "%s – %s" % (fmt_date(f), fmt_date(t))

    def _need_account(self, env):
        if "account.move.line" not in env:
            raise UserError(_("Accounting isn't installed in this Odoo."))

    def _sum(self, env, model, domain, field):
        r = env[model]._read_group(domain, [], [field + ":sum"])
        return (r[0][0] if r else 0.0) or 0.0

    # ---------- accounting ----------
    def _build_partner_ledger(self, env, p):
        self._need_account(env)
        partner = env["res.partner"].browse(p.get("partner_id")).exists()
        if not partner:
            raise UserError(_("Which customer or vendor? e.g. “ledger Acme this year”."))
        partner = partner.commercial_partner_id
        rt = env["yapie.report.type"].sudo().search([("code", "=", "partner_ledger")], limit=1)
        f, t = self.resolve_period(env, rt, p)
        dom = [("partner_id", "child_of", partner.id), ("parent_state", "=", "posted"), ("company_id", "=", env.company.id),
               ("account_id.account_type", "in", ("asset_receivable", "liability_payable"))]
        opening = self._sum(env, "account.move.line", dom + [("date", "<", f)], "balance") if f else 0.0
        lines = env["account.move.line"].search(dom + ([("date", ">=", f)] if f else []) + [("date", "<=", t)], order="date, move_id, id", limit=MAX_ROWS)
        cur = self._cur(env)
        rows, bal, dr, cr = [], opening, 0.0, 0.0
        if f:
            rows.append(["", _("Opening balance"), "", "", "", None, None, opening])
        for l in lines:
            bal += l.balance
            dr += l.debit
            cr += l.credit
            label = l.move_id.ref or (l.name if l.name and l.name != l.move_id.name else "") or ""
            rows.append([fmt_date(l.date), l.move_id.name or "", l.journal_id.code or "", label[:60],
                         fmt_date(l.date_maturity) if l.date_maturity and l.date_maturity != l.date else "", l.debit or None, l.credit or None, bal])
        state = _("owes you") if bal > 0.005 else _("you owe") if bal < -0.005 else _("settled")
        return {
            "title": _("Partner ledger"), "subtitle": "%s · %s" % (partner.name, self._period_text(f, t)), "currency": cur,
            "columns": [(_("Date"), "text"), (_("Entry"), "text"), (_("Journal"), "text"), (_("Reference"), "text"),
                        (_("Due"), "text"), (_("Debit"), "money"), (_("Credit"), "money"), (_("Balance"), "money")],
            "rows": rows, "totals": ["", _("Closing balance"), "", "", "", dr, cr, bal],
            "file_hint": partner.name, "truncated": len(lines) >= MAX_ROWS,
            "caption": _("Partner ledger · %(p)s · %(per)s\nClosing balance %(b)s (%(s)s)", p=partner.name, per=self._period_text(f, t), b=fmt_money(abs(bal), cur), s=state),
        }

    def _aging(self, env, p, kind):
        self._need_account(env)
        acc = "asset_receivable" if kind == "in" else "liability_payable"
        rt = env["yapie.report.type"].sudo().search([("code", "=", "receivable_aging" if kind == "in" else "payable_aging")], limit=1)
        _f, t = self.resolve_period(env, rt, p)
        dom = [("account_id.account_type", "=", acc), ("parent_state", "=", "posted"), ("reconciled", "=", False),
               ("amount_residual", "!=", 0), ("company_id", "=", env.company.id), ("date", "<=", t)]
        if p.get("partner_id"):
            dom.append(("partner_id", "child_of", env["res.partner"].browse(p["partner_id"]).commercial_partner_id.id))
        sign = 1 if kind == "in" else -1
        buckets = defaultdict(lambda: [0.0] * 6)
        for l in env["account.move.line"].search(dom, limit=50000):
            days = (t - (l.date_maturity or l.date)).days
            i = 0 if days <= 0 else 1 if days <= 30 else 2 if days <= 60 else 3 if days <= 90 else 4
            b = buckets[l.partner_id.commercial_partner_id.display_name or _("(no partner)")]
            b[i] += sign * l.amount_residual
            b[5] += sign * l.amount_residual
        items = sorted(buckets.items(), key=lambda kv: -kv[1][5])[:MAX_ROWS]
        rows = [[name] + [v or None for v in vals] for name, vals in items]
        tot = [sum(v[i] for _n, v in items) for i in range(6)]
        cur = self._cur(env)
        title = _("Receivables aging") if kind == "in" else _("Payables aging")
        return {
            "title": title, "subtitle": _("as of %s") % fmt_date(t), "currency": cur,
            "columns": [(_("Customer") if kind == "in" else _("Vendor"), "text"), (_("Not due"), "money"), (_("1–30"), "money"),
                        (_("31–60"), "money"), (_("61–90"), "money"), (_("Over 90"), "money"), (_("Total"), "money")],
            "rows": rows, "totals": [_("Total")] + tot,
            "caption": _("%(t)s as of %(d)s\nTotal %(a)s · overdue %(o)s · %(n)s parties", t=title, d=fmt_date(t), a=fmt_money(tot[5], cur), o=fmt_money(tot[5] - tot[0], cur), n=len(items)),
        }

    def _build_receivable_aging(self, env, p):
        return self._aging(env, p, "in")

    def _build_payable_aging(self, env, p):
        return self._aging(env, p, "out")

    def _build_overdue_invoices(self, env, p):
        self._need_account(env)
        today = fields.Date.context_today(env.user)
        dom = [("move_type", "=", "out_invoice"), ("state", "=", "posted"), ("payment_state", "in", ("not_paid", "partial")),
               ("invoice_date_due", "<", today), ("company_id", "=", env.company.id)]
        if p.get("partner_id"):
            dom.append(("partner_id", "child_of", env["res.partner"].browse(p["partner_id"]).commercial_partner_id.id))
        moves = env["account.move"].search(dom, order="invoice_date_due", limit=MAX_ROWS)
        rows = [[m.name, m.partner_id.display_name, fmt_date(m.invoice_date), fmt_date(m.invoice_date_due), (today - m.invoice_date_due).days, m.amount_residual_signed] for m in moves]
        total = sum(r[5] for r in rows)
        cur = self._cur(env)
        return {
            "title": _("Overdue invoices"), "subtitle": _("as of %s") % fmt_date(today), "currency": cur,
            "columns": [(_("Invoice"), "text"), (_("Customer"), "text"), (_("Date"), "text"), (_("Due"), "text"), (_("Days late"), "int"), (_("Amount due"), "money")],
            "rows": rows, "totals": [_("Total"), "", "", "", None, total],
            "caption": _("%(n)s overdue invoices · %(a)s", n=len(rows), a=fmt_money(total, cur)),
        }

    def _summary(self, env, p, kind):
        self._need_account(env)
        code = "sales_summary" if kind == "out" else "purchase_summary"
        rt = env["yapie.report.type"].sudo().search([("code", "=", code)], limit=1)
        f, t = self.resolve_period(env, rt, p)
        types = ("out_invoice", "out_refund") if kind == "out" else ("in_invoice", "in_refund")
        sign = 1 if kind == "out" else -1
        dom = [("move_type", "in", types), ("state", "=", "posted"), ("invoice_date", "<=", t), ("company_id", "=", env.company.id)]
        if f:
            dom.append(("invoice_date", ">=", f))
        if p.get("partner_id"):
            dom.append(("partner_id", "child_of", env["res.partner"].browse(p["partner_id"]).commercial_partner_id.id))
        groups = env["account.move"]._read_group(dom, ["partner_id"], ["__count", "amount_untaxed_signed:sum", "amount_tax_signed:sum", "amount_total_signed:sum"])
        rows = sorted(([pt.display_name or _("(no partner)"), n, sign * u, sign * x, sign * tt] for pt, n, u, x, tt in groups), key=lambda r: -r[4])
        tot = [sum(r[i] for r in rows) for i in (1, 2, 3, 4)]
        cur = self._cur(env)
        title = _("Sales by customer") if kind == "out" else _("Purchases by vendor")
        return {
            "title": title, "subtitle": self._period_text(f, t), "currency": cur,
            "columns": [(_("Customer") if kind == "out" else _("Vendor"), "text"), (_("Invoices") if kind == "out" else _("Bills"), "int"),
                        (_("Untaxed"), "money"), (_("Tax"), "money"), (_("Total"), "money")],
            "rows": rows[:MAX_ROWS], "totals": [_("Total")] + tot,
            "caption": _("%(t)s · %(p)s\n%(n)s documents · total %(a)s", t=title, p=self._period_text(f, t), n=int(tot[0]), a=fmt_money(tot[3], cur)),
        }

    def _build_sales_summary(self, env, p):
        return self._summary(env, p, "out")

    def _build_purchase_summary(self, env, p):
        return self._summary(env, p, "in")

    def _build_cash_bank(self, env, p):
        self._need_account(env)
        rt = env["yapie.report.type"].sudo().search([("code", "=", "cash_bank")], limit=1)
        _f, t = self.resolve_period(env, rt, p)
        groups = env["account.move.line"]._read_group(
            [("account_id.account_type", "=", "asset_cash"), ("parent_state", "=", "posted"), ("date", "<=", t), ("company_id", "=", env.company.id)],
            ["account_id"], ["balance:sum"])
        rows = sorted(([a.display_name, b] for a, b in groups), key=lambda r: r[0])
        total = sum(r[1] for r in rows)
        cur = self._cur(env)
        return {
            "title": _("Cash and bank"), "subtitle": _("as of %s") % fmt_date(t), "currency": cur,
            "columns": [(_("Account"), "text"), (_("Balance"), "money")], "rows": rows, "totals": [_("Total"), total],
            "caption": _("Cash and bank as of %(d)s: %(a)s", d=fmt_date(t), a=fmt_money(total, cur)),
        }

    # ---------- sales / inventory ----------
    def _build_sale_orders(self, env, p):
        if "sale.order" not in env:
            raise UserError(_("Sales isn't installed in this Odoo."))
        rt = env["yapie.report.type"].sudo().search([("code", "=", "sale_orders")], limit=1)
        f, t = self.resolve_period(env, rt, p)
        dom = [("state", "=", "sale"), ("company_id", "=", env.company.id), ("date_order", "<", fields.Datetime.to_datetime(t) + timedelta(days=1))]
        if f:
            dom.append(("date_order", ">=", fields.Datetime.to_datetime(f)))
        if p.get("partner_id"):
            dom.append(("partner_id", "child_of", env["res.partner"].browse(p["partner_id"]).commercial_partner_id.id))
        orders = env["sale.order"].search(dom, order="date_order", limit=MAX_ROWS)
        inv = dict(env["sale.order"]._fields["invoice_status"]._description_selection(env))
        rows = [[o.name, o.partner_id.display_name, fmt_date(o.date_order.date()), o.user_id.name or "", inv.get(o.invoice_status, ""), o.amount_total] for o in orders]
        total = sum(r[5] for r in rows)
        cur = self._cur(env)
        return {
            "title": _("Sales orders"), "subtitle": self._period_text(f, t), "currency": cur,
            "columns": [(_("Order"), "text"), (_("Customer"), "text"), (_("Date"), "text"), (_("Salesperson"), "text"), (_("Invoicing"), "text"), (_("Amount"), "money")],
            "rows": rows, "totals": [_("Total"), "", "", "", "", total],
            "caption": _("%(n)s confirmed orders · %(p)s · %(a)s", n=len(rows), p=self._period_text(f, t), a=fmt_money(total, cur)),
        }

    def _build_stock_onhand(self, env, p):
        if "stock.quant" not in env:
            raise UserError(_("Inventory isn't installed in this Odoo."))
        dom = [("location_id.usage", "=", "internal"), ("company_id", "=", env.company.id)]
        q = (p.get("text") or "").strip()
        if q:
            dom.append(("product_id", "in", env["product.product"]._search([("display_name", "ilike", q)])))
        groups = env["stock.quant"]._read_group(dom, ["product_id"], ["quantity:sum", "reserved_quantity:sum"])
        rows = sorted(([pr.display_name, pr.uom_id.name, qty, res, qty - res] for pr, qty, res in groups if abs(qty) > 1e-9), key=lambda r: r[0])[:MAX_ROWS]
        today = fields.Date.context_today(env.user)
        return {
            "title": _("Stock on hand"), "subtitle": (_("“%s” · ") % q if q else "") + _("as of %s") % fmt_date(today),
            "columns": [(_("Product"), "text"), (_("Unit"), "text"), (_("On hand"), "qty"), (_("Reserved"), "qty"), (_("Available"), "qty")],
            "rows": rows, "file_hint": q,
            "caption": _("Stock on hand%(q)s: %(n)s products", q=(" · " + q) if q else "", n=len(rows)),
        }

    # ---------- output ----------
    def _cell(self, v, kind, cur=""):
        if v is None or v == "":
            return ""
        if kind == "money":
            return "{:,.2f}".format(v)
        if kind == "qty":
            return ("{:,.3f}".format(v)).rstrip("0").rstrip(".")
        if kind == "int":
            return "{:,}".format(int(v))
        return str(v)

    def _pdf(self, data):
        cols = data["columns"]
        view = dict(data)
        view["head"] = [c[0] for c in cols]
        view["align"] = ["r" if c[1] in ("money", "qty", "int") else "l" for c in cols]
        view["body"] = [[self._cell(v, cols[i][1]) for i, v in enumerate(r)] for r in data["rows"]]
        view["foot"] = [self._cell(v, cols[i][1]) for i, v in enumerate(data["totals"])] if data.get("totals") else None
        view["landscape"] = len(cols) > 6
        ref = "yapie.action_yapie_table_report_landscape" if view["landscape"] else "yapie.action_yapie_table_report"
        pdf, _t = self.env["ir.actions.report"].sudo()._render_qweb_pdf(ref, res_ids=[], data={"doc": view})
        return pdf

    def _xlsx(self, data):
        import xlsxwriter
        out = io.BytesIO()
        wb = xlsxwriter.Workbook(out, {"in_memory": True})
        ws = wb.add_worksheet((data["title"] or "Report")[:31])
        title =wb.add_format({"bold": True, "font_size": 14})
        head = wb.add_format({"bold": True, "bg_color": "#EEF2F7", "border": 1})
        money = wb.add_format({"num_format": "#,##0.00"})
        qty = wb.add_format({"num_format": "#,##0.###"})
        tmoney = wb.add_format({"num_format": "#,##0.00", "bold": True, "top": 1})
        tbold = wb.add_format({"bold": True, "top": 1})
        ws.write(0, 0, data["title"], title)
        ws.write(1, 0, "%s · %s" % (data.get("company", ""), data.get("subtitle", "")))
        ws.write(2, 0, data.get("generated", ""))
        cols = data["columns"]
        for i, (label, kind) in enumerate(cols):
            ws.write(4, i, label + (" (%s)" % data["currency"] if kind == "money" and data.get("currency") else ""), head)
            ws.set_column(i, i, 14 if kind != "text" else 28)
        r = 5
        for row in data["rows"]:
            for i, v in enumerate(row):
                k = cols[i][1]
                if v is None or v == "":
                    continue
                ws.write_number(r, i, v, money if k == "money" else qty) if k in ("money", "qty", "int") and isinstance(v, (int, float)) else ws.write(r, i, v)
            r += 1
        if data.get("totals"):
            for i, v in enumerate(data["totals"]):
                k = cols[i][1]
                if isinstance(v, (int, float)) and k in ("money", "qty", "int"):
                    ws.write_number(r, i, v, tmoney if k == "money" else tbold)
                else:
                    ws.write(r, i, v or "", tbold)
        ws.freeze_panes(5, 0)
        wb.close()
        return out.getvalue()
