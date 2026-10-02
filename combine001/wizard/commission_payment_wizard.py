from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CommissionPaymentWizard(models.TransientModel):
    """BRD sec. 13.2: bulk 'mark as Paid' for a selection of Commission
    Report lines, recording the payment reference/date in one step
    instead of editing each line individually."""
    _name = 'combine001.commission.payment.wizard'
    _description = 'Mark Commission as Paid'

    line_ids = fields.Many2many('combine001.commission.line', 'combine001_comm_payment_wiz_line_rel',
                                 'wizard_id', 'line_id', string='Commission Lines',
                                 default=lambda self: [(6, 0, self.env.context.get('active_ids', []))])
    payment_id = fields.Many2one('account.payment', string='Payment Entry Reference')
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
        unpaid = self.line_ids.filtered(lambda l: l.payment_state != 'paid')
        if not unpaid:
            raise UserError(_('All selected lines are already Paid.'))
        if not self.payment_id and not self.payment_reference:
            raise UserError(_('Set a Payment Entry Reference or a Payment Reference.'))
        unpaid.write({
            'payment_state': 'paid',
            'payment_id': self.payment_id.id,
            'payment_reference': self.payment_reference,
            'payment_date': self.payment_date,
        })
        return {'type': 'ir.actions.act_window_close'}
