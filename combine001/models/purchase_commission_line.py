from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PurchaseCommissionLine(models.Model):
    """BRD for Purchase Module Changes sec. 10-13: a commission-agent
    process mirroring the Sales Module's combine001.commission.line, one
    row per Vendor Bill line linked back to a PO line. Unlike the sales
    side (a flat Unpaid/Paid), the BRD explicitly asks for a 4-state
    workflow here (Draft -> Confirmed -> Payable -> Paid, plus
    Cancelled) with "Payable" meaning the vendor itself has actually been
    paid - see `x_bill_paid` / `action_mark_payable`. `payment_status`
    still gives the simplified Paid/Unpaid view sec. 12 asks the report
    to show.
    """
    _name = 'combine001.purchase.commission.line'
    _description = 'Purchase Commission Line'
    _order = 'date desc, id desc'

    agent_id = fields.Many2one('combine001.commission.agent', required=True, string='Commission Agent')
    purchase_order_id = fields.Many2one('purchase.order', required=True, ondelete='cascade', string='Purchase Order')
    purchase_line_id = fields.Many2one('purchase.order.line', required=True, ondelete='cascade', string='PO Line')
    vendor_bill_id = fields.Many2one('account.move', required=True, ondelete='cascade', string='Vendor Bill')
    vendor_bill_line_id = fields.Many2one('account.move.line', required=True, ondelete='cascade', string='Vendor Bill Line')
    partner_id = fields.Many2one(related='purchase_order_id.partner_id', store=True, string='Vendor')
    product_id = fields.Many2one(related='purchase_line_id.product_id', store=True)
    quantity = fields.Float(related='purchase_line_id.product_qty', store=True)
    unit_price = fields.Float(related='purchase_line_id.price_unit', store=True)
    date = fields.Date(related='vendor_bill_id.invoice_date', store=True)
    commission_basis = fields.Selection(
        [('po_value', 'Purchase Order Value'),
         ('received_value', 'Received Value'),
         ('invoice_value', 'Vendor Invoice Value'),
         ('paid_value', 'Paid Invoice Value')],
        required=True, default='invoice_value', string='Commission Basis')
    rate = fields.Float(string='Rate (%)')
    base_amount = fields.Monetary(compute='_compute_amounts', store=True, string='Base Amount')
    commission_amount = fields.Monetary(compute='_compute_amounts', store=True, string='Commission Amount')
    currency_id = fields.Many2one(related='purchase_order_id.currency_id', store=True)
    company_id = fields.Many2one(related='purchase_order_id.company_id', store=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('payable', 'Payable'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True, copy=False, string='Status')
    payment_status = fields.Selection([
        ('unpaid', 'Unpaid'),
        ('paid', 'Paid'),
    ], compute='_compute_payment_status', store=True, string='Payment Status')
    x_bill_paid = fields.Boolean(compute='_compute_x_bill_paid', string='Vendor Bill Fully Paid')
    payment_id = fields.Many2one('account.payment', copy=False, string='Commission Payment Entry')
    payment_reference = fields.Char(copy=False, string='Payment Reference')
    payment_date = fields.Date(copy=False, string='Payment Date')

    _vendor_bill_line_uniq = models.Constraint(
        'UNIQUE(vendor_bill_line_id)',
        'A purchase commission line already exists for this vendor bill line.',
    )

    @api.depends('purchase_line_id.price_subtotal', 'purchase_line_id.qty_received', 'purchase_line_id.price_unit',
                 'vendor_bill_line_id.price_subtotal', 'vendor_bill_id.amount_total', 'vendor_bill_id.amount_residual',
                 'vendor_bill_id.amount_untaxed', 'rate', 'commission_basis')
    def _compute_amounts(self):
        for rec in self:
            basis = rec.commission_basis
            if basis == 'po_value':
                base = rec.purchase_line_id.price_subtotal
            elif basis == 'received_value':
                base = rec.purchase_line_id.qty_received * rec.purchase_line_id.price_unit
            elif basis == 'paid_value':
                bill = rec.vendor_bill_id
                ratio = (rec.vendor_bill_line_id.price_subtotal / bill.amount_untaxed) if bill.amount_untaxed else 0.0
                base = ratio * (bill.amount_total - bill.amount_residual)
            else:  # invoice_value
                base = rec.vendor_bill_line_id.price_subtotal
            rec.base_amount = base
            rec.commission_amount = base * (rec.rate or 0.0) / 100.0

    @api.depends('state')
    def _compute_payment_status(self):
        for rec in self:
            rec.payment_status = 'paid' if rec.state == 'paid' else 'unpaid'

    @api.depends('vendor_bill_id.payment_state')
    def _compute_x_bill_paid(self):
        for rec in self:
            rec.x_bill_paid = rec.vendor_bill_id.payment_state in ('paid', 'in_payment')

    def action_confirm(self):
        for rec in self:
            if rec.state != 'draft':
                continue
            rec.state = 'confirmed'

    def action_mark_payable(self):
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError(_('Only a Confirmed commission can be marked Payable.'))
            if not rec.x_bill_paid:
                raise UserError(_('The underlying Vendor Bill must be fully paid before this commission becomes Payable.'))
            rec.state = 'payable'

    def action_cancel(self):
        for rec in self:
            if rec.state == 'paid':
                raise UserError(_('A Paid commission cannot be cancelled.'))
            rec.state = 'cancelled'

    def action_mark_paid(self):
        for rec in self:
            if rec.state == 'paid':
                raise UserError(_('%s is already marked as Paid.', rec.display_name))
            if rec.state != 'payable':
                raise UserError(_('Only a Payable commission can be marked as Paid.'))
            if not rec.payment_id and not rec.payment_reference:
                raise UserError(_('Set a Commission Payment Entry or a Payment Reference before marking as Paid.'))
            if not rec.payment_date:
                raise UserError(_('Set a Payment Date before marking as Paid.'))
        self.write({'state': 'paid'})
