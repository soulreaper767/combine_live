from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CommissionLine(models.Model):
    _name = 'combine001.commission.line'
    _description = 'Commission Line'
    _order = 'date desc, id desc'

    agent_id = fields.Many2one('combine001.commission.agent', required=True, string='Commission Agent')
    sale_order_id = fields.Many2one('sale.order', required=True, ondelete='cascade', string='Sales Order')
    sale_line_id = fields.Many2one('sale.order.line', required=True, ondelete='cascade', string='Sales Order Line')
    invoice_id = fields.Many2one('account.move', required=True, ondelete='cascade', string='Invoice')
    invoice_line_id = fields.Many2one('account.move.line', required=True, ondelete='cascade', string='Invoice Line')
    partner_id = fields.Many2one(related='sale_order_id.partner_id', store=True, string='Customer')
    product_id = fields.Many2one(related='sale_line_id.product_id', store=True, string='Product')
    date = fields.Date(related='invoice_id.invoice_date', store=True)
    base = fields.Selection(related='sale_order_id.commission_base', store=True, string='Commission Base')
    base_amount = fields.Monetary(string='Base Amount')
    rate = fields.Float(string='Rate (%)')
    commission_amount = fields.Monetary(string='Commission Amount')
    currency_id = fields.Many2one(related='sale_order_id.currency_id', store=True)
    company_id = fields.Many2one(related='sale_order_id.company_id', store=True)

    # -- Payment tracking (BRD sec. 13.2/13.3) ----------------------------
    payment_state = fields.Selection([
        ('unpaid', 'Unpaid'),
        ('paid', 'Paid'),
    ], default='unpaid', required=True, copy=False, string='Payment Status')
    payment_id = fields.Many2one('account.payment', copy=False, string='Payment Entry Reference',
                                  help='The vendor payment made to the Commission Agent, if recorded through '
                                       'Accounting. Optional - a plain reference/date is enough where the agent '
                                       'is not set up as a full vendor.')
    payment_reference = fields.Char(copy=False, string='Payment Reference')
    payment_date = fields.Date(copy=False, string='Payment Date')
    amount_outstanding = fields.Monetary(compute='_compute_amounts', store=True, string='Outstanding Commission')
    amount_paid = fields.Monetary(compute='_compute_amounts', store=True, string='Paid Commission')

    _invoice_line_uniq = models.Constraint(
        'UNIQUE(invoice_line_id)',
        'A commission line already exists for this invoice line.',
    )

    @api.depends('commission_amount', 'payment_state')
    def _compute_amounts(self):
        for rec in self:
            if rec.payment_state == 'paid':
                rec.amount_paid = rec.commission_amount
                rec.amount_outstanding = 0.0
            else:
                rec.amount_paid = 0.0
                rec.amount_outstanding = rec.commission_amount

    def action_mark_paid(self):
        """BRD sec. 13.2: when the commission payment is entered/confirmed,
        mark the record Paid with its payment reference/date so it stops
        showing as unpaid. Exposed directly here for a single record;
        combine001.commission.payment.wizard drives the same write for a
        bulk selection."""
        for rec in self:
            if rec.payment_state == 'paid':
                raise UserError(_('%s is already marked as Paid.', rec.display_name))
            if not rec.payment_id and not rec.payment_reference:
                raise UserError(_('Set a Payment Entry Reference or a Payment Reference before marking as Paid.'))
            if not rec.payment_date:
                raise UserError(_('Set a Payment Date before marking as Paid.'))
        self.write({'payment_state': 'paid'})
