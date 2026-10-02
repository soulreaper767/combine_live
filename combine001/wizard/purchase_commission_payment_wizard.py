from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PurchaseCommissionPaymentWizard(models.TransientModel):
    """Bulk 'mark as Paid' for a selection of Purchase Commission lines -
    mirror of combine001.commission.payment.wizard (sales side)."""
    _name = 'combine001.purchase.commission.payment.wizard'
    _description = 'Mark Purchase Commission as Paid'

    line_ids = fields.Many2many('combine001.purchase.commission.line', 'combine001_purch_comm_pay_wiz_line_rel',
                                 'wizard_id', 'line_id', string='Commission Lines',
                                 default=lambda self: [(6, 0, self.env.context.get('active_ids', []))])
    payment_id = fields.Many2one('account.payment', string='Commission Payment Entry')
    payment_reference = fields.Char()
    payment_date = fields.Date(required=True, default=fields.Date.context_today)
    total_amount = fields.Monetary(compute='_compute_total_amount')
    currency_id = fields.Many2one(related='line_ids.currency_id')

    @api.depends('line_ids.commission_amount')
    def _compute_total_amount(self):
        for wiz in self:
            wiz.total_amount = sum(wiz.line_ids.mapped('commission_amount'))

    def action_confirm(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Select at least one Commission line.'))
        payable = self.line_ids.filtered(lambda l: l.state == 'payable')
        if not payable:
            raise UserError(_('None of the selected lines are Payable (confirm them and mark Payable first).'))
        if not self.payment_id and not self.payment_reference:
            raise UserError(_('Set a Commission Payment Entry or a Payment Reference.'))
        payable.write({
            'state': 'paid',
            'payment_id': self.payment_id.id,
            'payment_reference': self.payment_reference,
            'payment_date': self.payment_date,
        })
        return {'type': 'ir.actions.act_window_close'}
