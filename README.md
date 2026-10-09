# Combine001 (Live — customizations only, no data)

**This is `combine_live`, the live-server variant of the `combine001`
module.** It contains every behavioural customization from that repo —
price locks, approval workflows, commission processes, GST/withholding
tax automation, document renaming, etc. — plus, unlike the rest of this
module's original design, it DOES import this company's own real Chart
of Accounts (structure only, no opening trial balance), Debtors/
Creditors control accounts, 2,476 customers, 346 vendors, and the Yarn
product catalog - sourced directly from the live server's own exports,
not the `combine001` repo's bundled demo-company CSVs. See the "Chart
of Accounts" and "Live Debtors, Vendors & Finished Goods" sections
below for exactly what each import does. It still does NOT import
opening balances or anything from `combine001`'s own bundled demo
data.

If you need the full-import variant (e.g. for a fresh demo/UAT
database with its own self-contained demo data instead of this
company's real exports), see the `combine001` repo instead.

Odoo 19 custom app implementing the "Odoo ERP Enhancements v1.0" BRD
(Sibyl Technologies, for Combine Spinning, 2026-09-16).

## Layout

- `combine001/` — the Odoo module (installable, `application: True`). All
  configuration, security groups, views and menus load automatically when
  the module is installed — no manual setup steps required.

## What it implements

| BRD Section | Feature | Where |
|---|---|---|
| 5.1 | Sales Order price-change approval workflow + audit trail | `models/sale_order.py` |
| 5.1.2 / 5.2 | Quotation qty ceiling, item-wise & customer-wise qty limits | `models/sale_order.py`, `models/product_template.py`, `models/customer_item_limit.py` |
| 5.3 | Cumulative delivery quantity validation | `models/stock_move.py` |
| 5.4 | Cumulative invoice quantity validation | `models/account_move.py` |
| 5.5 | Sales Tax Template | native Odoo `account.tax` — no custom code needed |
| 5.6 | Additional charges (freight/transport/handling/service) | `models/charge_type.py`, `wizard/add_charge_wizard.py` |
| 5.7 | Commission Agent + automatic commission calc on invoice | `models/commission_agent.py`, `models/commission_line.py`, `models/account_move.py` |
| 5.8 | Chart of Accounts restructuring + real opening trial balance import | `models/res_company.py`, data in `data/import/` |
| 7 | Separate Tax Ledger + controlled manual adjustment | `views/tax_ledger_views.xml`, `models/tax_adjustment.py` |
| 10 | Security groups (Tax Officer, Auditor) + audit trail via chatter | `security/combine001_security.xml` |
| 3.1 | One demo user per defined role, pre-assigned to the right groups | `data/combine001_users_data.xml` |
| — | "Quotation" relabeled to "Contract", confirmed order to "Delivery Order" | `views/sale_quotation_to_contract_views.xml`, `views/sale_order_to_delivery_order_views.xml` |
| — | Finished Goods / Raw Material product catalog import | `models/res_company.py`, data in `data/import/` |
| — | GST 18%/22% Sale+Purchase taxes, defaulting to 18% | `models/res_company.py`, `models/account_tax.py` |
| — | "GST Saved" — notional GST tracking when no GST is charged | `models/gst_saving.py`, `models/account_move.py`, `views/gst_saving_views.xml` |
| — | Purchase BRD: RFQ/PO approval + price/qty lock + PO Amendment | `models/purchase_order.py`, `models/purchase_amendment.py` |
| — | Purchase BRD: Receipt + Vendor Bill approval workflow | `models/combine001_approval_mixin.py`, `models/stock_picking.py`, `models/account_move.py` |
| — | Purchase BRD: Purchase Commission Agent (Draft→Confirmed→Payable→Paid) | `models/purchase_commission_line.py` |

## Chart of Accounts

`_combine001_import_coa` (runs first, before everything below) imports
this company's own real Chart of Accounts - **700 accounts**,
`data/import/coa.csv`: `code, name, account_type, reconcile`, built
from `D:\Others\Combine Spinning\coatoimport.xlsx` (a direct
Code/Account Name/Type/Allow Reconciliation/Account Currency export
from the live server's own Accounting > Chart of Accounts list, "Type"
mapped from its display label - e.g. "Receivable" - to the internal
selection value - e.g. `asset_receivable`). From the 1,017 rows in
that export:
- **2 stray generic-chart leftovers dropped** (`400000 Product Sales`,
  `251000 Tax Received`) - the export itself accidentally picked these
  up, recognisable the same way as everywhere else in this file: every
  one of this company's own real codes is dotted (`3.09.01`,
  `4.01.01.0001`), the generic chart's never are.
- **323 "party-wise" Receivable/Payable leaf accounts dropped** - one
  GL account per individual customer/vendor (e.g. `3.09.01.0106 HAJI
  ASHRAF ALI ANSARI`, `2.07.06.0011 OLYMPIA TEXTILE INTERNATIONAL -
  COMMISSION AGENT`) - this company does not want a separate account
  per party in the Chart of Accounts. Only the **23 control-level**
  Receivable/Payable accounts (3-segment codes, e.g. `3.09.01`,
  `2.07.09`) remain; every customer/vendor is tracked through Odoo's
  native Partner Ledger instead (see "Live Debtors" below and
  `_combine001_ensure_default_accounts`).
- **8 Debtors sub-ledger control codes added** -
  `3.09.03/.05/.06/.07/.08/.09/.10/.12` - that genuinely don't exist
  even in the real export (only individual party-wise leaf accounts
  existed under them, now also dropped per the point above), merged in
  so this file is the single, complete source of truth for every
  Debtors control account, not just the 6 the real export happened to
  already have at the group level.

**Structure only - no opening balances are posted** (the source export
carries no opening_debit/opening_credit column at all), same
"stage 1 is master data only" discipline as the Yarn product catalog
below. A full opening trial balance, if wanted later, is a separate,
deliberate piece of work.

**Full replace, every upgrade:** any account on this company whose
code isn't in `coa.csv` is removed (unlinked if nothing references it
yet, archived instead if something already does - e.g. a posted tax
entry); clearing any company/journal/`ir.default` reference to it
first so the delete isn't blocked. Everything that IS in the file
always has its name/type/reconcile overwritten to match - `coa.csv` is
the single source of truth, including correcting any placeholder name
this module may have guessed before this import existed (e.g. `3.09.01`
was first created by `_combine001_ensure_debtor_control_accounts` as
"DEBTORS - LOCAL"; the real export's name is "TRADE DEBTORS - LOCAL
SALES (GENERAL)").

**Default accounts** (`_combine001_ensure_default_accounts`, runs
right after): replacing the whole chart every upgrade blanks out every
company/journal field that pointed at whatever just got removed - this
re-sets the ones with an unambiguous, defensible answer:
- `company.transfer_account_id` → `3.14.01.0001 CASH IN HAND - HEAD
  OFFICE` (Odoo's internal-transfer technical account - any real
  bank/cash account works here, it's just plumbing).
- Company-wide default Receivable (`ir.default` on
  `res.partner.property_account_receivable_id`) → `3.09.01 TRADE
  DEBTORS - LOCAL SALES (GENERAL)` - the fallback for any
  customer that doesn't get a specific sub-ledger from the Live
  Debtors import below (and the control account every new customer's
  master data shows by default).
- Company-wide default Payable (`ir.default` on
  `res.partner.property_account_payable_id`) → `2.07.09 CREDITORS -
  OTHERS` - same role on the vendor side; this repo doesn't import a
  vendor list, so this is every vendor's default payable control
  account unless manually overridden.
- `account.journal` of type `sale` → `default_account_id` =
  `4.01.01.0001 LOCAL SALES - YARN` (the one real product line this
  company actually sells).

Deliberately NOT auto-set, logged as a warning instead listing exactly
which journals still need one: `bank`/`cash`/`purchase`-type journals'
`default_account_id`. There are 30 real bank accounts and 11
split-by-fibre raw-material purchase accounts in the Chart of Accounts
- which one a given Bank/Cash/Purchase journal should default to is a
real decision, not something to guess at from the account name alone.

## Live Debtors (Customers), Vendors & Finished Goods (Yarn) data

Unlike the rest of this repo, these imports DO ship real data —
`data/import/customers.csv` / `debtor_groups.csv` / `vendors.csv` /
`products.csv`, sourced directly from the live server's own
`CUSTOMERS LIST.xlsx`, `Vendors List.xlsx` and `Products List
FINAL.xlsx` (plus an earlier `PRODUCTS LIST WITH INVENTORY BALANCE.xls`
sheet, since superseded — see Products below). Run on every
install/upgrade, same idempotent find-or-update pattern as everything
else in this file.

**Customers** (`_combine001_import_live_customers`): 2,476 unique
customers (2,492 rows in the source, 16 exact name+account duplicates
collapsed), each linked to its own one of the **14 Debtors control
accounts** (`3.09.01`–`3.09.14`, one per sub-ledger: Local, Export,
Waste, Raw Material, Bad Debts Recoverables, Rotation, Others,
Foreign, Export Business, Fabrics Venture, Combine Fabrics, Revive
Business-Local, Revive Stitched Garments, Revive Stitching Services) —
see the "Chart of Accounts" section above for how those 14 control
accounts themselves are sourced/created, and why no party-wise GL
account per customer exists at all. This import only sets each
customer's OWN specific sub-ledger account; the company-wide default
(`3.09.01`, for any customer/vendor this repo doesn't otherwise cover)
is handled by `_combine001_ensure_default_accounts` instead.

**Vendors** (`_combine001_import_live_vendors`): 346 vendors from
`Vendors List.xlsx`, each linked to its own one of the **9 Creditors
control accounts** (`2.07.01`/`.02`/`.03`/`.04`/`.05`/`.07`/`.08`/`.09`/`.13`
— Raw Material, Rags/Waste, Machinery/Assets, Stores, Contractors,
Purchase Brokerage, Services, Others, Export Business) — same
discipline as Customers above; all 9 control accounts already exist in
`coa.csv`, so unlike the Debtors side nothing new needs creating here.

**Products** (`_combine001_import_live_products`): **149 Yarn
products**, sourced from the live server's own "Products List
FINAL.xlsx" — supersedes an earlier 126-item list sourced from
"PRODUCTS LIST WITH INVENTORY BALANCE.xls" (30-9 sheet), which this
same method now also retires: any existing Yarn-category product whose
name isn't in the current `products.csv` is unlinked (archived instead,
if something still references it and unlink is blocked). All under one
*Yarn* category (parent *Finished Goods*), posting to `4.01.01.0001
LOCAL SALES - YARN` / `5.18.02.0002` / `3.08.01.0001` — this company's
own real account codes (same ones the full-import variant's
`product_categories.csv` also uses), found-and-reused if they already
exist on this database, **created at those exact codes if they don't**
(`_combine001_ensure_yarn_category`, same find-or-create idiom as the
structural GST Saving/Withholding accounts and the Debtors control
accounts above — master data only, no opening balance posted either
way). Item names standardised: whitespace collapsed, spelling typos
fixed (`TWWERA`→`TWEERA`, `AUTAIRO`/`AUTOAIR`→`AUTOAIRO`), unmatched
stray parentheses dropped. The source file carries no quantity data at
all (unlike the previous list's reference-only bag counts), so there's
nothing to decide re: opening stock either way. UoM is Odoo's generic
*Units*. No prices — products import at price 0 for Sales/Finance to
fill in.

## Products, Categories & Chart of Accounts mapping (full-import variant only)

**Not applicable to this `combine_live` repo** beyond the Debtors/Yarn
import documented just above. This section (kept below for reference,
describing the `combine001` repo's full-import variant) documents a
much larger product-catalog/CoA/opening-balance import that this build
deliberately does NOT perform.

**The source file is a daily stock/production report, not a product
list or price list** — two sheets ("Finished Goods", "Raw Material"),
each a snapshot of opening/production/dispatch/closing quantities by
material family, re-grouped inconsistently across the sheet (the same
category name reappears several times, e.g. "MIX MATERIAL YARN" 3
times). `data/import/product_categories.csv` and `products.csv` are the
*cleaned* output of studying and parsing that report (see the category
mapping table below) — not re-parsed from the workbook at install time.

**What got created:**
- **18 product categories** in 2 families — *Finished Goods* (11
  yarn-material categories + Socks/Cloth/Towel) and *Raw Material* (6
  fiber-type categories) — each with `property_valuation = 'periodic'`
  (matches how this company's existing Chart of Accounts already works:
  "Raw Material Consumed" as a direct expense, "Stock in Trade" as a
  plain asset, no interim/GRNI accounts anywhere — this is a periodic/
  manual-valuation books, not Odoo's automated perpetual model, so
  `periodic` was the correct choice, not `real_time`).
- **284 products** (172 Finished Goods + 117 Raw Material minus 5 exact
  name collisions across categories in the source report — kept the
  first occurrence of each, see the comment in the CSV generation), all
  `type='consu', is_storable=True`, UoM **KG** (the only unit that's
  actually consistent across the source data — "Bags"/"Cones"/"Bales"
  each convert to a different KG weight per product, so KG was the only
  safe uniform choice).
- Every category's Income/Expense(COGS)/Stock accounts are mapped onto
  the **already-imported real Chart of Accounts** wherever a specific
  match existed (e.g. Raw Material > Cotton → `5.01.01.0002 RAW MATERIAL
  CONSUMED - COTTON` / `3.08.03.0001 RAW MATERIAL STOCK COTTON`, Raw
  Material sales → the existing `4.01.01.0002 LOCAL SALES - RAW
  MATERIAL`, all Yarn categories → the existing `4.01.01.0001 LOCAL
  SALES - YARN`). Where no matching account existed yet, a small,
  clearly-new one was added in an unused code slot next to its natural
  siblings (Finished Goods had no Stock/COGS accounts at all yet, Socks
  had no Income account, Lycra had no Consumption account despite
  already having a Stock account) — see `_STRUCTURAL_ACCOUNTS` in
  `models/res_company.py` for the full list and reasoning, and the GST
  section below for the other 2 new accounts.
- **No prices.** The source report has zero pricing data (it's a
  quantity report) — products import at price 0, for Sales/Finance to
  fill in.
- **No opening stock quantities.** The report's quantity columns are a
  point-in-time snapshot mixed with monthly production/dispatch deltas,
  not something safe to import as "current stock" without risking a
  materially wrong inventory count — only product *master data* is
  created here. Loading real opening stock quantities (with a costing
  method and a proper opening inventory adjustment) is a separate,
  follow-on piece of work if wanted.

## GST 18%/22% and "GST Saved"

Four `account.tax` records (`models/res_company.py`
`_combine001_ensure_gst_taxes`, tagged `x_combine001_gst=True` via
`models/account_tax.py` so the GST-Saved logic below can recognize
them): **GST 18% (Sale)**, **GST 22% (Sale)**, **GST 18% (Purchase)**,
**GST 22% (Purchase)** — posting to the Chart of Accounts' existing
`3.11.05.0002 SALES TAX PAYABLE - OUTPUT` / `3.11.05.0001 SALES TAX
REFUNDABLE - INPUT` accounts respectively. **18% is the default** for
both directions (company + every imported product) since the source
data doesn't say which specific items need 22% — flip those manually
once known (product's Sales/Purchase tab, or Accounting > Taxes).

**Sale-side rate now follows the buyer's GST registration status**
(follow-up request): FBR charges a higher rate on supplies to
unregistered buyers, so a Contract/Delivery Order line or a Sales Invoice
line no longer just takes whatever GST tax is configured on the
product — `models/account_tax.py`'s `_combine001_swap_gst_for_buyer`
swaps in **18% if the customer's Tax Info tab says Registered, 22% if
Unregistered** (the field's own default), overriding
`sale.order.line._compute_tax_ids` and
`account.move.line._compute_tax_ids` (`models/sale_order.py` /
`models/account_move.py`) on top of Odoo's normal product-tax default,
so it also live-recomputes if the customer on an existing
order/invoice is changed. Purchase-side GST (what a vendor charges us)
is untouched — "buyer" here always means our own customer. Existing
records aren't retroactively rewritten, only new/recomputed lines.

**"GST Saved":** whenever a customer invoice or vendor bill (or credit
note/refund) is **posted with no GST charged at all**,
`models/account_move.py`'s `_combine001_create_gst_saving_line` computes
what GST *would* have applied — for each line, using whichever of the 4
GST taxes is configured on that line's product master (`taxes_id` for
sales, `supplier_taxes_id` for purchases; a line whose product has no
GST tax configured contributes nothing, there's no rate to fall back on)
— and records the total as a same-amount entry:

```
Dr  3.13.01.0001  GST Saving            (Current Asset)
Cr  1.09.01.0001  GST Saving Reserve    (Equity)
```

posted immediately (own journal entry, Miscellaneous Operations
journal), linked back to the source invoice/bill via a
`combine001.gst.saving.line` record — *Combine001 > Taxation > GST
Saved*, **invoice/bill-wise**: list view grouped by Sale/Purchase then
Customer/Vendor (drop the grouping, or add "Invoice/Bill", to see every
individual entry), each row showing the source invoice/bill and
partner directly, with a running total; the form view (click a row) has
"Open Invoice/Bill" and "Open GST Saving Entry" buttons; the pivot view
can drill Sale/Purchase → Customer/Vendor → Invoice/Bill by month. This
is **deliberately kept out of the real P&L** (it never touches an
income/expense account) — a pure memo/management metric of the value of
off-GST-books trade, not a real tax liability or saving.

**Where it shows on the Balance Sheet** (*Accounting > Reporting >
Balance Sheet*, verified against a real posted entry):
- `GST Saving` → **ASSETS > Current Assets** (verified: `9,000.00`
  appeared there for a test entry)
- `GST Saving Reserve` → **EQUITY (& EARNINGS) > Equity**, as the
  **last line** in that section — sorting after Retained Earnings /
  Profit Distribution (groups `1.03`/`1.05`), which is what "below
  Profit/(Loss) for the period" could reasonably ask for from the CoA
  side. One honest caveat: Odoo's own Balance Sheet renders "Equity"
  (static accounts, incl. this one) as a section that comes *before* its
  own separate, computed "Earnings" section (Current Year Unallocated
  Earnings = the live Profit/(Loss) figure) — so in the rendered report
  specifically, GST Saving Reserve sits just *above* that Earnings
  section, not literally under the number itself. It's still the very
  last, clearly separated line before it, which is as close as the
  report's own fixed structure allows.

**Seeing the impact with vs. without GST Saving:** rather than hacking a
checkbox into Odoo's Enterprise financial-report engine (a real,
version-fragile undertaking for a niche need), the *GST Saved* report
gives a direct running total, and because both accounts are isolated in
their own dedicated groups (`3.13`, `1.09`) with no sibling accounts,
the standard Balance Sheet's own line-folding already lets you
collapse/expand exactly these two lines to see the delta directly — the
simpler, safer answer to "give me an easy way to see the impact."

## "Quotation" → "Contract", "Sales Order" → "Delivery Order"

Combine Spinning's trade calls these documents "contracts", not
"quotations" — and per the **Change Request Document for Sales Module**
(2026-09-28), the confirmed order is now called a **Delivery Order**
(superseding the module's earlier "Sales Contract" wording with plain
"Contract", to match that document's exact naming table).

`views/sale_quotation_to_contract_views.xml` relabels the draft/sent
side: the main menu (*Sales > Orders > Contracts*), list/search view
titles, search filters ("My Contracts"), the "Set to Contract" button,
the "Mark Contract as Sent" action, the CRM Team "New Contract" button,
Quotation Templates ("Contract Templates"), the generated PDF filename
(`Contract - S00001.pdf`), and the PDF report body itself (title
"Contract #", "Contract Date" label).

`views/sale_order_to_delivery_order_views.xml` relabels the confirmed
side the same way: the *Sales > Orders > Orders* menu and its action,
list/calendar/graph/pivot view titles, the "Sales Orders"/"My Orders"
search filters, the CRM Team kanban dashboard's "Sales Orders" links,
the PDF filename (`Delivery Order - S00001.pdf`) and report body (title
"Delivery Order #", "Delivery Order Date" label) — a single
`ir.actions.report.print_report_name` expression covers both branches
(`'Contract - %s' or 'Delivery Order - %s'`), owned by this file since a
plain field can't be split across two data files the way template
xpaths can.

**Purely cosmetic**, both ways — the underlying `sale.order` model, its
fields, states (`draft`/`sent`/`sale`), and the whole quotation→order
workflow are completely unchanged; only the text a user sees is
different. A "Delivery Order" here is **not** the same document as a
"Delivery Challan" (see the next section) — it's the confirmed
Contract/`sale.order` itself, still one record, one document.

Not renamed: the Print-menu action's own technical label (still shows
"PDF Quote" — that's set by the Enterprise `sale_pdf_quote_builder`
module, which happens to load after combine001 and silently wins that one
field; not worth forcing a fight over a rarely-seen label via a fake
dependency), and anything outside the core Sales app (Subscriptions, POS,
Website/eCommerce, email template wording) — out of scope per the chosen
rename scope.

**Contract Date, properly trackable** (follow-up request): core Odoo
hides the draft/sent Quotation Date behind `base.group_no_one`
(developer mode only) on the form, and its Quotations list shows record
*Creation* Date instead of the actual document date — its own
assumption that a quotation's date isn't normally worth a regular user's
attention before confirmation. Not true here: a Contract is a formal,
date-significant document from day one, so `date_order` (`sale.order`'s
native date field, `_order = 'date_order desc, id desc'` by default —
records already sort newest-first by it) is now:
- **Visible and editable on the form for every user**, not just in
  debug mode (`views/sale_quotation_to_contract_views.xml` replaces the
  restricted label/field outright rather than just renaming them),
  labeled "Contract Date".
- **A default-visible column on the Contracts list**, labeled "Contract
  Date" (Creation Date kept as an optional, hidden-by-default column
  rather than dropped).
- **The "Group By" date option on the Contracts search**, relabeled
  from "Order Date" to "Contract Date" (the Delivery Orders search
  keeps its own separate wording for the same underlying filter).

## Contract → Delivery Order → Delivery Challan → Gate Pass → Sales Invoice

Implements `BRD for sales.docx`, since refined by the **Change Request
Document for Sales Module** (2026-09-28). A "Contract" is a `sale.order`
in `draft`/`sent` state; a "Delivery Order" is the same record once
confirmed (`state == 'sale'`) — see the naming section above. No separate
Contract model was introduced — the BRD's own title describes the change
as mapping this flow onto "the existing quotation-to-delivery process",
and Odoo's native Quotation→Order transition already *is* that first
step.

A standalone "Delivery Out" document originally sat between the
Delivery Order and the Delivery Challan (mirroring the confirmed order's
lines with no stock impact, purely for reference). The Change Request
explicitly asked for it to be **removed** ("a separate/new Delivery Out
document should not be created as part of the revised workflow") — the
Delivery Challan (`stock.picking`) is now created directly from the
confirmed Delivery Order by Odoo's own native procurement, exactly as
vanilla Odoo already does when a Sales Order confirms. Removed
entirely: `models/delivery_out.py`, `views/delivery_out_views.xml`, its
menu item, its two smart buttons/create-button on the Delivery Order
form, and the `x_delivery_out_id` field that used to link a Delivery
Challan back to it (a Delivery Challan links back to its Delivery Order
directly via the native `sale_id` field instead).

**Price lock.** Once a Contract is confirmed, `sale.order.line.write()`
(`models/sale_order.py`) blocks any `price_unit`/`product_uom_qty` change
outright (`UserError`, points the user at a Contract Amendment instead).
The same lock is mirrored on draft invoice lines linked to a Contract
line (`models/account_move.py`, `AccountMoveLine.write()`) — posted
invoices are correctly left alone; a posted invoice is fixed with a
credit note, not silently rewritten.

**Contract Amendment** (`models/sale_amendment.py`,
`combine001.sale.amendment` + `.line`) is the only door through that
lock: draft → submit → Sales Manager approval → Apply. Applying writes
straight onto the *same* existing `sale.order.line` record (never
creates a second line for a line being revised — a genuinely new product
can also be added through the same amendment), re-baselines
`x_quoted_price`/`x_quoted_qty` so the pre-existing "can't exceed the
quotation" guard (BRD SO-005/SO-006, unrelated feature) keeps working
against the new number afterward, pushes the revised price onto any
still-draft invoice lines already raised against that line, and chatter-
logs every apply with user/date/old→new values.

**Delivery Challan** is the *existing* `stock.picking`/Delivery Note
functionality, technically untouched (still the only document that
deducts stock, still only on validation) and cosmetically relabeled
"Delivery Challan" — same technique as the Quotation rename, plus a
`stock.picking.type._get_code_report_name()` override so the PDF title
follows too, and a one-time idempotent rename of each warehouse's
outgoing `stock.picking.type.name` (real per-company data, done in
`res_company._combine001_rename_delivery_picking_types`, not a fixed XML
id). Gained fields: the 3 registration-status fields, and
`x_contract_price` on each `stock.move`
(`related='sale_line_id.price_unit'`). Since it's raised directly by
native Odoo procurement from the confirmed Delivery Order, there is
exactly one `stock.move` per order line — no duplication risk, and
nothing extra for this module to guard against.

**No duplicate lines, anywhere in the chain** (Change Request sec. 6):
Contract → Delivery Order is the same record (a state change, not a new
document, so there's nothing to duplicate); Delivery Order → Delivery
Challan is Odoo's own native procurement, which has always created
exactly one `stock.move` per order line; Delivery Challan → Sales
Invoice is Odoo's own native invoicing, which has always created one
invoice line per order line (per the configured invoicing policy); and a
Contract Amendment (below) always writes onto the existing line instead
of creating a new one. None of this needed new code — removing the
Delivery Out document (the one place that maintained its own separate,
manually-mirrored line set) was the only piece that could have
introduced any duplication risk in the first place.

**Gate Pass** (`models/gate_pass.py`, `combine001.gate.pass` + `.line`)
is created from a *validated* (`state == 'done'`) outgoing Delivery
Challan via a button on the picking form. One per Delivery Challan
(DB unique constraint on `picking_id`) — no stock impact, lines mirror
the challan's own `stock.move`s via `related` fields.

**Unit of Measure** (Change Request sec. 2.1/8): Odoo already has a UoM
field on every relevant line (`sale.order.line.product_uom_id`,
`stock.move.product_uom`, `account.move.line.product_uom_id`) and already
carries it forward automatically between documents (native behaviour,
no custom code needed) — it's just hidden by default behind the "Units
of Measure & Packagings" feature toggle (Settings > General Settings).
`res_company._combine001_ensure_uom_group()` grants `uom.group_uom` to
`base.group_user` (Internal User) directly — exactly what that Settings
checkbox does under the hood — so UoM shows on the Contract/Delivery
Order, Delivery Challan and Sales Invoice for every user, out of the
box; a small extra view override (`views/account_move_uom_views.xml`)
forces the invoice line list's UoM column to always show rather than
leaving it as a user-hideable "optional" column. PDF reports already
include the same fields, so they pick it up automatically too. Verified
a newly-created Internal User has the group via `has_group()` (the
literal `group_ids` field only holds *directly* assigned groups —
`all_group_ids`/`has_group()` is what resolves the full implied-group
closure, including this one).

**Tax Info tab** (`models/res_partner.py`, `views/res_partner_views.xml`)
replaces the BRD's flat Registered/Unregistered checkbox pair with a
separate status per tax regime — GST, Income Tax, PRA — since this
business actually tracks all three independently. All 3 flow onto every
document above via `models/combine001_tax_status_mixin.py`
(`combine001.tax.status.mixin`, an `AbstractModel` with 3
`related(..., store=True)` Selection fields against `partner_id`, mixed
into `sale.order`, `stock.picking` and `account.move`; Gate Pass declares
the same 3 fields directly since its `partner_id` is itself `related`).
PRA status is deliberately the odd one out: it's
hidden on a document (`x_show_pra_status`, computed per model from that
document's own lines) unless at least one line's product has the new
`product.template.x_pra_applicable` flag set (Sales tab) — most of this
business is goods (GST), not services (PRA).

**Commission Report payment tracking** (`models/commission_line.py`):
`payment_state` (Unpaid/Paid), `payment_id`/`payment_reference`/
`payment_date`, and computed `amount_outstanding`/`amount_paid` (BRD
sec. 13.3's explicit ask). Marked Paid either per-record
(`action_mark_paid`) or in bulk from the Commission Report list's Action
menu (`combine001.commission.payment.wizard`).

## Withholding tax automation on Payments

Follow-up request on top of the BRD. `combine001.withholding.rate`
(`models/withholding_rate.py`) is one row per Vendor/Customer + date
range: a standard `rate`, and an optional exemption for that period with
its own `exempt_rate` (can be 0% for a full exemption) — rates can
therefore change over time and a partner's exemption certificate expires
back to the standard rate automatically, purely by date. "purchase" =
the rate WE withhold paying that Vendor; "sale" = the rate THAT CUSTOMER
is expected to withhold paying us (tracked from our own side, since we
don't see their books).

**Accounting mechanism.** `account.payment` gains `x_wht_applicable`,
`x_wht_rate`, `x_wht_amount` (computed) and `x_wht_account_id`
(`models/account_payment.py`). Rather than hand-building extra journal
lines, this overrides Odoo core's own `_prepare_move_withholding_lines`
— a documented no-op stub that exists in core `account` specifically for
this ("payment net of tax withheld"): the framework already reduces the
liquidity (bank) line by the withholding amount while the counterpart
(payable/receivable) line still clears the FULL invoice amount, so the
override only needs to return the withholding line itself, sign flipped
by direction (credit the Withholding Payable liability, purchase side /
debit the Withholding Receivable asset, sale side). Verified by
literally reading the posted `account.move.line`s: paying a PKR 1,180
GST-bearing bill at 10% correctly posts Dr Payable 1,180 / Cr Bank 1,062
/ Cr Withholding Tax Payable 118 — the bank line, not the payable, absorbs
the withholding.

**CoA accounts** (`models/combine001_constants.py`): purchase-side reuses
an **existing** leaf account from the real imported CoA — `2.12.01.0001
TAX AT SOURCE - PARTIES`, sitting in the CoA's own `2.12 TAX AT SOURCE`
liability group, an exact match for "tax withheld from party payments,
not yet remitted". Sale-side has no existing leaf, only a matching empty
group (`3.11.03 ADVANCE INCOME TAX AGAINST LOCAL SUPPLIES`) — one new
leaf account (`3.11.03.0001`, same name, asset) is created there, same
`_STRUCTURAL_ACCOUNTS` mechanism as the GST Saving accounts.

**Purchase-side "applicable by default".** A bare `account.payment` has
no reliable way to know which bill it's settling until it's actually
reconciled. The normal path — clicking **Register Payment** on a posted
bill — does know, so `account.payment.register._create_payment_vals_from_wizard`
is overridden to set `x_wht_applicable = True` by default exactly when
the bill being paid actually carries one of this module's GST taxes
(`account.move._combine001_has_gst_charged`), and to default `x_wht_rate`/
`x_wht_account_id` from the rate table for that vendor/date either way.
A manually-created payment (no invoice context) instead falls back to a
plain `partner_id`/`payment_type`/`date` onchange that defaults the rate/
account but leaves `x_wht_applicable` for the user to tick.

**Withholding Tax Variance report** (Combine001 > Taxation): BRD ask —
"see if customer deducted more or less than the amount that must have
been deducted". Every inbound (customer) payment also computes
`x_wht_expected_rate`/`x_wht_expected_amount` fresh from the rate table
for its own date, independent of whatever was actually entered, plus
`x_wht_variance = actual - expected`; the report is simply
`account.payment` filtered to customer payments with a "Variance Only"
search filter, list + pivot.

**Known pre-existing gap this depends on** (documented above under Chart
of Accounts, not new here): since the generic CoA auto-install is
deliberately cancelled, `res.company.transfer_account_id` and each
partner's `property_account_receivable_id`/`property_account_payable_id`
are never auto-seeded, and Odoo needs at least one of those to register
*any* payment at all (withholding or not). A human sets these once from
Accounting > Configuration before payments (with or without withholding)
can be used — same category of "left for a human to wire before go-live"
gap as the bank-journal defaults already noted above.

Verified: fresh install + 2 upgrade cycles clean, and a full functional
test (24 assertions) covering CoA account reuse/creation, the rate
table's overlap constraint, purchase-side auto-default from a real
GST-bearing bill through the actual Register Payment wizard with the
resulting journal entry checked line-by-line, sale-side expected-vs-
actual variance math (including an intentionally over-withheld case),
an exemption period resolving to its reduced rate then correctly
expiring back to no-rate, and the variance report's own domain — all
passing.

## RFQ → PO → Receipt → Vendor Bill → Payment → Commission (Purchase Module)

Implements `BRD for Purchase Module Changes in Odoo.docx`. An "RFQ" is a
`purchase.order` in `draft`/`sent` state; a "PO" is the same record
confirmed (`state == 'purchase'`) - no separate RFQ/PO models, same
reasoning as Contract/Delivery Order on the sales side.

**RFQ/PO approval - native, not custom.** Unlike Receipt and Vendor
Bill (below), Odoo already ships a near-identical mechanism for exactly
this: `company.po_double_validation` routes `button_confirm()` through a
`'to approve'` state gated to `purchase.group_purchase_manager` before
it becomes a PO. `res_company._combine001_ensure_po_approval()` forces
this on unconditionally (amount threshold 0, so it applies regardless
of value, not just above a limit) rather than layering a second,
redundant approval state on top of `purchase.order`.
`models/purchase_order.py` reinforces the native `button_approve()` with
an explicit Python-level group check (the native button is only guarded
by a view-level `groups=`, bypassable via RPC) and adds the two audit
fields Odoo doesn't track natively (`x_approved_by` - `date_approve`
already exists; `x_rejection_reason`, captured by a new
`action_combine001_reject()` that wraps `button_draft()`).

**Price/quantity lock** (BRD sec. 5): once confirmed, `purchase.order.line.write()`
blocks `product_id`/`price_unit`/`product_qty` changes outright, same
pattern as the Contract price lock. The only door through it is a
**PO Amendment** (`models/purchase_amendment.py`,
`combine001.purchase.amendment` + `.line`) — draft → submit → Purchase
Manager approval → apply, writing onto the *same* existing line (never
duplicates), chatter-logged.

At Receipt level (sec. 5.3), the *approved* quantity (`stock.move.product_uom_qty`,
the "Demand") is locked the same way once linked to a confirmed PO -
but the *actual received* quantity (`quantity`) is deliberately left
alone, since that's exactly how Odoo already models a short/excess/
partial receipt (via backorders) without altering the approved figure.
At Vendor Bill level (sec. 5.4), `account.move.line.write()` (already
guarded for the sales side) gained the same lock for bill lines linked
back to a `purchase_line_id`.

**Receipt and Vendor Bill approval - custom, because no native
equivalent exists.** Unlike RFQ/PO, Odoo has no manager-approval gate
before `stock.picking.button_validate()` or `account.move.action_post()`
for a bill. `models/combine001_approval_mixin.py`
(`combine001.approval.mixin`) provides a generic Draft → Submitted →
Approved → Rejected state machine with its own audit trail
(submitted/approved/rejected by + when), mixed into `stock.picking`
(scoped to incoming transfers actually linked to a Purchase Order -
Delivery Challans and plain internal transfers are untouched) and
`account.move` (scoped to `in_invoice`/`in_refund` - Sales Invoices are
untouched). Each inheriting model supplies which group may approve
(Purchase Manager for Receipts, Accounts Manager for Vendor Bills, per
BRD sec. 17's role table) and calls `_combine001_check_approved()` from
its own `button_validate()`/`action_post()` override.

**Purchase Commission** (sec. 10-13): reuses the same
`combine001.commission.agent` master as the sales side (it was already
generic). A new `combine001.purchase.commission.line`
(`models/purchase_commission_line.py`) is created per Vendor Bill line
linked back to a PO line, once the bill posts - unlike the sales side's
flat Unpaid/Paid, the BRD explicitly asks for a 4-state workflow here:

- **Draft** - just generated.
- **Confirmed** - reviewed and locked in (manual action).
- **Payable** - the *vendor* has actually been paid in full
  (`x_bill_paid`, computed from the bill's own `payment_state`) - a
  manual `action_mark_payable()` rather than a silent auto-transition,
  consistent with how the sales side's commission is also always marked
  Paid explicitly, not magically.
- **Paid** - the *commission* itself has been paid to the agent, via
  the same bulk "Mark as Paid" wizard pattern as the sales side
  (`combine001.purchase.commission.payment.wizard`, payment
  reference/date).

`commission_basis` (configurable per PO, sec. 10.2's explicit ask) picks
what the percentage applies against - PO value, received value
(`qty_received × price_unit`), vendor invoice value, or paid value (the
proportional share of whatever's actually been paid against the bill so
far, live-recomputed as payments apply) - `base_amount`/
`commission_amount` are both stored computes so they stay correct
automatically as the underlying PO/receipt/payment data changes. A
simplified `payment_status` (Paid/Unpaid) field gives the flat view
sec. 12 asks the report to show, alongside the full `state`.

**Duplicate-line prevention** (sec. 21, same reasoning as the sales
side's Change Request): satisfied natively once there's no extra
document layer duplicating lines - Odoo's own procurement creates one
`stock.move` per PO line, one commission line is guarded by a DB unique
constraint on `vendor_bill_line_id`, and a PO Amendment always writes
onto the existing line.

**New security roles** (sec. 17): Purchase User / Purchase Manager
(wrapping native `purchase.group_purchase_user`/`_manager`, same
Combine001-branded-group pattern as every other role in this module) -
Warehouse User and Accountant/Finance Manager (sec. 17's Warehouse User
and Accounts User/Manager) already existed and are reused as-is.

Verified: fresh install + 2 upgrade cycles clean, and a 32-assertion
functional test covering the full chain end-to-end - non-manager RFQ
confirmation routing to "to approve", a blocked non-manager approval
attempt, the price lock, a PO amendment changing the approved price,
the Receipt approval gate blocking validation until approved, the
demand-qty lock vs. a freely-different actual-received qty, the Vendor
Bill approval gate (and confirming a Purchase Manager specifically
*cannot* approve a bill, only an Accounts Manager can), the purchase
commission's full Draft→Confirmed→Payable→Paid lifecycle gated on the
vendor bill actually being paid, and the bulk payment wizard - all
passing.

## Roles & demo users (BRD Section 3.1)

Every BRD role gets its own **Combine001-branded security group**
(`security/combine001_security.xml`), organized into 6 privileges (rows) —
Sales, Warehouse, Accounting, Tax, Audit, Administration — all under one
"Combine001" category, so the whole access matrix is manageable from a
single block on *Settings > Users & Companies > Users > (user) > Access
Rights*, instead of being scattered across native Sales/Inventory/
Accounting/Settings sections. Being separate privileges (rows) means a
user can hold a selection from **each** at once (e.g. Sales Manager +
Finance Manager simultaneously) — they aren't mutually exclusive.

Each of these wraps (via `implied_ids`) the real native Odoo group(s) that
grant the actual functional access, so assigning the Combine001-branded
role is enough on its own for a real (UI-assigned) user — no need to also
manually tick the underlying native group:

| Privilege | Role | Wraps |
|---|---|---|
| Sales | Sales User | `sales_team.group_sale_salesman` |
| Sales | Sales Manager | + `sales_team.group_sale_manager` |
| Warehouse | Warehouse User | `stock.group_stock_user` |
| Accounting | Accountant | `account.group_account_user` |
| Accounting | Finance Manager | + `account.group_account_manager` |
| Tax | Tax Officer | `account.group_account_user` |
| Audit | Auditor | — (Combine001-only read access, see below) |
| Administration | **Module Admin** *(new)* | full CRUD on Combine001's own models (quantity limits, charge types, commission agents, tax ledger adjustments) — no access to the rest of Odoo |
| Administration | System Administrator | Module Admin + `base.group_system` |

One demo user per role is created on install, already in the right
group(s):

| Role | Login |
|---|---|
| Sales User | `sales.user@combine001.local` |
| Sales Manager | `sales.manager@combine001.local` |
| Warehouse / Inventory User | `warehouse.user@combine001.local` |
| Accountant | `accountant@combine001.local` |
| Finance Manager / Controller | `finance.manager@combine001.local` |
| Tax Officer | `tax.officer@combine001.local` |
| Module Admin | `module.admin@combine001.local` |
| System Administrator | `system.admin@combine001.local` |
| Auditor | `auditor@combine001.local` (read-only on Sales Orders, Invoices,
  Payments, Deliveries and every Combine001 model — see `views/audit_views.xml`) |

**No password is set** — these are placeholder accounts committed to a
public git repo, and a hardcoded password there would be a credential
leak. After install, a System Administrator sets each one's password
locally via *Settings > Users & Companies > Users > (user) > Action >
Change Password*, or triggers *Send Password Reset Instructions* if
outgoing mail is configured. They're meant as a starting point for
setup/UAT — rename, reassign, or deactivate them and create real named
accounts once the client's staff list is confirmed.

Each demo user's `group_ids` still lists the full closure of groups
explicitly (both the Combine001-branded role group *and* the native
group(s) it wraps) rather than relying on `implied_ids` to cascade
automatically: testing on this Odoo 19 build showed `implied_ids` does
not propagate to a user created via a plain `(6, 0, [...])` write on
`group_ids` in XML data (it works fine for a real user assigned a role
through the Users UI — only XML-created users need this workaround) —
see the comment in `data/combine001_users_data.xml`.

## Chart of Accounts, opening trial balance, Customers & Vendors, bank accounts

**Not applicable to this `combine_live` repo** — this entire section
(kept below for reference) describes the `combine001` repo's
full-import variant. `combine_live` has no `data/import/` directory at
all and never touches the Chart of Accounts, opening balance, Customers,
Vendors, or bank journals; this server's real data is expected to
already be in place through its own separate process.

`models/res_company.py`'s `_combine001_run_import()` replaces the company's
Chart of Accounts and opening trial balance with the client's actual data
— extracted from `D:\Others\Combine Spinning\coa and opening trial.xlsx`
(Chart of Accounts sheet, a Delta ERP trial balance with levels, as on
15-Sep-2026) and `D:\Others\Combine Spinning\Customers and Vendors.xlsx`.
The cleaned data it imports from is bundled at `data/import/*.csv`
(generated once from those two workbooks, not re-read from them at
install/upgrade time).

**Runs on install AND on every module upgrade** — wired via a
non-`noupdate` `<function>` tag (`data/combine001_import_run.xml`), not
`post_init_hook`: `post_init_hook` only ever fires on a fresh install,
never on `-u`/Upgrade, which is why the data didn't show up after the
first deploy on a database where the module was already installed before
this feature existed. The whole thing is written to be safe to re-run
on every future upgrade too:

- Accounts, account groups, bank journals and Customers/Vendors are all
  **found-or-created by their natural key** (code / name) instead of
  blindly recreated, so re-running never produces duplicates.
- Until the opening balance is posted (see below), every run does a
  **full, clean rebuild**: any pre-existing journal entries for the
  company are cleared first (see step 1) so accounts/groups/opening
  balances always come out correct and consistent — no partial/stale
  leftovers, no "only some of it shows up."
- Opening balances are (re)computed via Odoo's native
  `opening_debit`/`opening_credit` fields — the same mechanism Odoo's own
  CSV-import UI uses — every time the pre-posted rebuild runs, right after
  the reset in step 1 clears whatever the previous run's lines were, so
  there's never a stale line for Odoo's own auto-balancing mechanism to
  collide with. (Setting these fields doesn't build the move
  synchronously — it queues a precommit callback — so the import forces
  an `env.cr.flush()` before posting, otherwise `account_opening_move_id`
  reads back empty.)
- Once the opening move has actually been **posted** (i.e. the business
  has gone live on this data), a later upgrade **skips the Chart of
  Accounts / opening balance / currency part entirely** rather than
  resetting and rewriting live financial data — logged as a warning.
  Customers, Vendors and bank journals still refresh normally either way.

**What it does, step by step:**

1. Unless the opening move is already posted (skip straight to step 6 if
   so — see above): **clears every existing journal entry** for the
   company, posted or draft (unposts first if needed). This is what
   actually fixes "only 2 lines show in the Trial Balance" and "still in
   USD" — both were caused by leftover entries from *before* this import
   ever completed correctly (e.g. Odoo's own fallback CoA auto-install,
   step 3, completing before this module's fix was in place, or ad hoc
   testing) sitting there blocking things: Odoo's Trial Balance/General
   Ledger/Balance Sheet only show *posted* entries by default, so with
   the real 1,007-account opening balance stuck in draft, only those
   stray entries were visible; and Odoo flatly refuses to change company
   currency while *any* `account.move.line` exists at all (posted or
   draft) — including this import's own opening balance from a prior run,
   which is why the currency fix kept silently failing after the very
   first attempt.
2. Sets the company currency to **PKR**, now that step 1 has cleared
   anything that would block it (activates the PKR currency record if
   needed). Also force-updates anything else that stores its **own**
   currency independently instead of following the company automatically
   — a default `product.pricelist` in particular is auto-created by
   `product`/`sale_management` using whatever the company's currency
   happened to be at that exact moment, which can be stale (still USD
   from before this module ever ran, even after the company itself is
   correctly PKR) — and any `account.journal` with a stray non-PKR
   currency override gets cleared back to "follow company currency".
3. Cancels Odoo's own fallback "auto-install a generic Chart of Accounts"
   behaviour, which would otherwise create a *second*, competing default
   CoA and journals for any company with no localization chosen (see the
   big comment on `_combine001_cancel_generic_coa_auto_install` — this was
   the one genuinely surprising Odoo 19 internal to work around).
4. Creates a `Miscellaneous Operations` (general), `Customer Invoices`
   (sale) and `Vendor Bills` (purchase) journal if the company doesn't
   already have one of each — needed for day-to-day invoicing and for the
   opening move itself.
5. Imports **126 account groups** (Level 1–3 of the source CoA) and
   **1,007 accounts** (Level 4 posting accounts) with their opening
   balances, then **posts the opening move** — real opening balances (a
   ~21.4 billion Rs trial balance) would ideally be reviewed by a Finance
   Manager before posting, but it's posted automatically here so the data
   actually shows up in every standard report; any residual rounding is
   auto-balanced by Odoo against the equity "Undistributed Profits"
   account. Once posted, it's protected from every future rebuild (see
   above) — a correction after that point should be a proper reviewed
   accounting adjustment, not another module upgrade silently rewriting
   it.
6. **Debtors/Creditors control accounts (BRD COA-001/002/003):** instead
   of importing the source's 331 individual vendor-named and 33
   individual customer-named GL leaf accounts, this creates one **control
   account** per named sub-group instead (e.g. "CREDITORS-RAW MATERIAL",
   "DEBTORS - EXPORT"), each carrying that sub-group's own rolled-up
   opening balance from the source trial balance — mathematically
   identical to the sum of the individual accounts it replaces (verified:
   the two differ by Rs 1 out of ~21.4 billion, pure floating-point
   rounding in the source spreadsheet). Customer/vendor-level detail is
   tracked the Odoo-native way instead: via `partner_id` on the journal
   item (Partner Ledger), not a separate GL account per party. Any
   pre-existing account whose code is not part of this import gets
   archived (not deleted — other configs may reference it).
7. **Bank/cash accounts and journals:** every one of the ~30 real, named
   accounts under "CASH AND BANK BALANCE" is imported as its own GL
   account (like any other posting account, step 5) *and* gets its own
   `account.journal` (type `bank` or `cash`, per whether its code is under
   `3.14.01.*` "Cash in Hand"), linked via `default_account_id`. The one
   with the single largest opening debit balance is marked as the default
   (lowest `sequence`, so it's the one every journal/payment picker shows
   first) — currently "MEEZAN BANK 0204-0100906298".
8. Imports the **341 customers** and **346 vendors** from the Customers
   and Vendors workbook as `res.partner` Contacts (`customer_rank`/
   `supplier_rank` set), each with `property_account_receivable_id` /
   `property_account_payable_id` pointing at the correct control account
   — determined from that party's *original* code prefix in the source
   workbook (e.g. a vendor coded under `2.07.01.xxxx` gets the
   "CREDITORS-RAW MATERIAL" control account), even though the new account
   codes themselves ignore those old numbers, per the ask. A party whose
   original group has no named control account (most customers — see
   below) falls back to one general control account each: `3.09.01`
   "TRADE DEBTORS - LOCAL SALES (GENERAL)" for customers, the existing
   `2.07.09` "CREDITORS - OTHERS" for vendors. Runs every time regardless
   of whether the opening move is posted, so party master data always
   stays current.

**Note on data completeness:** the source CoA workbook explicitly excludes
"dormant" accounts (both Debit and Credit closing balance in {0, 1, 2} Rs)
from the *balance* extract — see its Notes sheet. Most customers (308 of
341) fall under debtor sub-groups that got excluded this way (their
balances had fully netted out by the snapshot date), which is why they
route to the one general control account above rather than a named
sub-group; only 15 of 346 vendors are in the equivalent situation. This
does **not** mean those parties are missing — the Customers and Vendors
workbook is unfiltered, so all of them are imported as Contacts either
way; only the not-currently-meaningful GL sub-group distinction is
collapsed for them.

**Not done automatically, by design** (would require guessing at real
business specifics this data doesn't contain): rewiring the *other*
company-level default-account settings (cash-difference accounts,
early-payment-discount accounts, product category default income/expense
accounts, tax repartition line accounts, fiscal positions) that a prior
chart-of-accounts template may have set to now-archived accounts, and
deciding whether the auto-picked default bank journal (largest opening
balance) is actually the one that should be used going forward. Review
Accounting > Configuration before go-live.

## Assumptions made for the BRD's open items (Section 12)

The BRD explicitly leaves six points open for client sign-off. This module
ships a working default for each so the app is usable end-to-end now;
change these in code once the client confirms:

1. **Quantity hierarchy precedence** — all applicable limits (quotation
   qty, item limit, customer+item limit) are enforced independently; the
   most restrictive one blocks first.
2. **Price-override approval** — flat rule: *any* price change away from
   the quoted price on a draft/sent order routes to a Sales Manager.
3. **Invoicing policy** — order-based: invoice quantity is validated
   against the Sales Order quantity (not delivered quantity).
4. **Commission base** — configurable per Commission Agent / Sales Order
   (`sales_value` / `product_value` / `quantity` / `net_sales_value`);
   defaults to Sales Value. `product_value` and `net_sales_value` are
   currently computed the same as `sales_value` (invoice line subtotal).
5. **Customer accounting dimension** — uses Odoo's native `partner_id` on
   journal items (Partner Ledger / Aged Receivable reports already give
   customer-wise detail); no new dimension model was added.
6. **Tax Ledger adjustment approval** — single level: Finance Manager
   approves. Approval only marks the request Approved — it does not
   auto-post a journal entry, since the actual GL accounts to use are
   part of the still-open Chart of Accounts restructuring (COA-003); the
   Accountant posts the entry manually referencing the approved record.

## Install / Upgrade

Addon lives under `~/odoo/custom/` (symlinked as `combine001` ->
`combine001_odoo/combine001`) on the WSL Odoo dev instance, addons path
already includes `~/odoo/custom`. Fresh install:

```
odoo-bin -c <conf> -d <db> -i combine001 --stop-after-init
```

Upgrade an already-installed database to pick up code/data changes
(including a re-run of the CoA/opening-balance/Customers&Vendors import,
per the safety rules described above):

```
odoo-bin -c <conf> -d <db> -u combine001 --stop-after-init
```

On Odoo.sh or any web-based install, the equivalent is: push to the
tracked branch, then in that database's backend go to **Apps**, clear the
"Apps" filter, search **Combine001**, and click **Upgrade** (not just
confirm it's installed — Upgrade is what re-runs the import).
