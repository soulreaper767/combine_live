from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .combine001_constants import GST_SAVING_ASSET_CODE, GST_SAVING_EQUITY_CODE

_GST_MOVE_TYPES = ('out_invoice', 'out_refund', 'in_invoice', 'in_refund')


class AccountMove(models.Model):
    _name = 'account.move'
    _inherit = ['account.move', 'combine001.tax.status.mixin', 'combine001.approval.mixin']

    x_sale_order_id = fields.Many2one(
        'sale.order', compute='_compute_x_sale_order_id', string='Contract / Sales Order', store=True)
    x_show_pra_status = fields.Boolean(compute='_compute_x_show_pra_status')

    @api.depends('invoice_line_ids.sale_line_ids.order_id')
    def _compute_x_sale_order_id(self):
        for move in self:
            move.x_sale_order_id = move.invoice_line_ids.sale_line_ids.order_id[:1]

    def _combine001_approval_group(self):
        return 'account.group_account_manager'

    @api.depends('invoice_line_ids.product_id.x_pra_applicable')
    def _compute_x_show_pra_status(self):
        for move in self:
            move.x_show_pra_status = bool(move.invoice_line_ids.product_id.filtered('x_pra_applicable'))

    def _combine001_has_gst_charged(self):
        """Used by account_payment.py to default 'Is Withholding
        Applicable' on the payment-registration wizard: True if any
        line on this invoice/bill actually carries one of this module's
        GST taxes (not just a product with a GST rate configured -
        that's the GST Saving feature's fallback, this checks what was
        really charged)."""
        self.ensure_one()
        return any(t.x_combine001_gst for line in self.invoice_line_ids for t in line.tax_ids)

    def action_post(self):
        invoices = self.filtered(lambda m: m.move_type == 'out_invoice')
        bills = self.filtered(lambda m: m.move_type in ('in_invoice', 'in_refund'))
        gst_relevant = self.filtered(lambda m: m.move_type in _GST_MOVE_TYPES)
        for move in invoices:
            move._combine001_check_invoice_qty()
        bills._combine001_check_approved(_('posted'))
        res = super().action_post()
        for move in invoices:
            move._combine001_create_commission_lines()
        for move in bills:
            move._combine001_create_purchase_commission_lines()
        for move in gst_relevant:
            move._combine001_create_gst_saving_line()
        return res

    def _combine001_check_invoice_qty(self):
        self.ensure_one()
        for line in self.invoice_line_ids:
            sale_line = line.sale_line_ids[:1]
            if not sale_line:
                continue
            other_qty = sum(self.env['account.move.line'].search([
                ('sale_line_ids', 'in', sale_line.id),
                ('move_id.state', '=', 'posted'),
                ('move_id.move_type', '=', 'out_invoice'),
                ('id', '!=', line.id),
            ]).mapped('quantity'))
            if other_qty + line.quantity > sale_line.product_uom_qty:
                raise UserError(_(
                    "Cumulative invoiced quantity for %(product)s "
                    "(%(total)s) would exceed the Sales Order quantity "
                    "(%(ordered)s) on order %(order)s.",
                    product=sale_line.product_id.display_name,
                    total=other_qty + line.quantity, ordered=sale_line.product_uom_qty,
                    order=sale_line.order_id.name,
                ))

    def _combine001_create_commission_lines(self):
        self.ensure_one()
        CommissionLine = self.env['combine001.commission.line']
        for line in self.invoice_line_ids:
            sale_line = line.sale_line_ids[:1]
            if not sale_line:
                continue
            order = sale_line.order_id
            if not order.commission_agent_id:
                continue
            if CommissionLine.search_count([('invoice_line_id', '=', line.id)]):
                continue
            base = order.commission_base or order.commission_agent_id.default_base
            rate = order.commission_rate or order.commission_agent_id.default_rate
            base_amount = line.quantity if base == 'quantity' else line.price_subtotal
            commission_amount = base_amount * (rate or 0.0) / 100.0
            CommissionLine.create({
                'agent_id': order.commission_agent_id.id,
                'sale_order_id': order.id,
                'sale_line_id': sale_line.id,
                'invoice_id': self.id,
                'invoice_line_id': line.id,
                'base_amount': base_amount,
                'rate': rate,
                'commission_amount': commission_amount,
            })

    def _combine001_create_purchase_commission_lines(self):
        """Mirror of _combine001_create_commission_lines for the
        purchase side (BRD for Purchase Module Changes sec. 10) - the
        actual base_amount/commission_amount are computed live on
        combine001.purchase.commission.line itself (depends on the
        configured commission_basis), not here; this only creates the
        record, once, per bill line linked back to a PO line."""
        self.ensure_one()
        PurchaseCommissionLine = self.env['combine001.purchase.commission.line']
        for line in self.invoice_line_ids:
            purchase_line = line.purchase_line_id
            if not purchase_line:
                continue
            order = purchase_line.order_id
            if not order.commission_agent_id:
                continue
            if PurchaseCommissionLine.search_count([('vendor_bill_line_id', '=', line.id)]):
                continue
            PurchaseCommissionLine.create({
                'agent_id': order.commission_agent_id.id,
                'purchase_order_id': order.id,
                'purchase_line_id': purchase_line.id,
                'vendor_bill_id': self.id,
                'vendor_bill_line_id': line.id,
                'rate': order.commission_rate or order.commission_agent_id.default_rate,
                'commission_basis': order.commission_basis,
            })

    def _combine001_create_gst_saving_line(self):
        """If this invoice/bill has NO GST charged on it at all, compute
        what GST would have applied - using the rate configured on each
        line's product master (sale: taxes_id, purchase: supplier_taxes_id,
        whichever of the 4 GST taxes this module manages is set there) -
        and record it as "GST Saved": a same-amount Dr GST Saving (Current
        Asset) / Cr GST Saving Reserve (Equity) entry, kept entirely
        outside the real P&L (it never touches an income/expense account),
        purely for management visibility into the value of off-GST-books
        trade. A line whose product has no GST tax configured at all
        contributes nothing (there's no rate to use)."""
        self.ensure_one()
        if self.move_type not in _GST_MOVE_TYPES:
            return
        if self.env['combine001.gst.saving.line'].search_count([('move_id', '=', self.id)]):
            return

        is_sale = self.move_type in ('out_invoice', 'out_refund')
        tax_field = 'taxes_id' if is_sale else 'supplier_taxes_id'

        total_base = 0.0
        total_gst = 0.0
        for line in self.invoice_line_ids:
            if not line.product_id:
                continue
            if any(t.x_combine001_gst for t in line.tax_ids):
                continue  # real GST already charged on this line
            product_gst_taxes = line.product_id[tax_field].filtered('x_combine001_gst')
            if not product_gst_taxes:
                continue  # no GST rate configured on this product to fall back on
            rate = product_gst_taxes[0].amount
            total_base += line.price_subtotal
            total_gst += line.price_subtotal * rate / 100.0

        if not total_gst:
            return

        company = self.company_id
        Account = self.env['account.account']
        asset_account = Account.search([
            ('company_ids', 'in', company.id), ('code', '=', GST_SAVING_ASSET_CODE),
        ], limit=1)
        equity_account = Account.search([
            ('company_ids', 'in', company.id), ('code', '=', GST_SAVING_EQUITY_CODE),
        ], limit=1)
        journal = self.env['account.journal'].search([
            ('company_id', '=', company.id), ('type', '=', 'general'),
        ], limit=1)
        if not (asset_account and equity_account and journal):
            return

        label = _("GST Saved - %(move)s", move=self.name or self.ref or 'Draft')
        entry = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': self.invoice_date or self.date,
            'ref': label,
            'line_ids': [
                (0, 0, {
                    'account_id': asset_account.id, 'partner_id': self.partner_id.id,
                    'name': label, 'debit': total_gst, 'credit': 0.0,
                }),
                (0, 0, {
                    'account_id': equity_account.id, 'partner_id': self.partner_id.id,
                    'name': label, 'debit': 0.0, 'credit': total_gst,
                }),
            ],
        })
        entry.action_post()

        self.env['combine001.gst.saving.line'].create({
            'move_id': self.id,
            'journal_entry_id': entry.id,
            'direction': 'sale' if is_sale else 'purchase',
            'base_amount': total_base,
            'rate': (total_gst / total_base * 100.0) if total_base else 0.0,
            'gst_amount': total_gst,
        })


class AccountMoveLine(models.Model):
    """BRD sec. 9/11 (sales) and BRD for Purchase Module Changes sec. 5.4
    (purchase): the Contract/PO-approved price flows to the Sales
    Invoice/Vendor Bill and cannot be manually overridden there either -
    only a Contract/PO amendment (applied with the
    combine001_amendment_apply context, see sale_amendment.py /
    purchase_amendment.py) may change it. Only enforced while the
    invoice/bill is still draft: once posted it's a real financial
    record, corrected the normal accounting way (credit note), not
    rewritten."""
    _inherit = 'account.move.line'

    @api.depends('move_id.partner_id.x_gst_status')
    def _compute_tax_ids(self):
        super()._compute_tax_ids()
        for line in self:
            if line.move_id.is_sale_document(include_receipts=True):
                line.tax_ids = line.tax_ids._combine001_swap_gst_for_buyer(line.move_id.partner_id, line.move_id.company_id)

    def write(self, vals):
        if ('price_unit' in vals or 'quantity' in vals) and not self.env.context.get('combine001_amendment_apply'):
            for line in self:
                if line.move_id.state != 'draft':
                    continue
                if line.sale_line_ids and line.move_id.move_type == 'out_invoice':
                    raise UserError(_(
                        "%(product)s: the price/quantity on this invoice line comes "
                        "from a Contract and cannot be changed directly. Use a "
                        "Contract Amendment instead.",
                        product=line.product_id.display_name,
                    ))
                if line.purchase_line_id and line.move_id.move_type in ('in_invoice', 'in_refund'):
                    raise UserError(_(
                        "%(product)s: this price/quantity is locked because the related RFQ "
                        "has been confirmed. Please use the approved amendment process to "
                        "make changes.",
                        product=line.product_id.display_name,
                    ))
        return super().write(vals)
