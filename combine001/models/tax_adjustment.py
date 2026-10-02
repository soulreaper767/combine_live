from odoo import _, api, fields, models
from odoo.exceptions import UserError


class TaxAdjustment(models.Model):
    _name = 'combine001.tax.adjustment'
    _description = 'Manual Tax Ledger Adjustment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(default='New', copy=False, readonly=True)
    tax_id = fields.Many2one('account.tax', required=True, string='Tax', tracking=True)
    partner_id = fields.Many2one('res.partner', string='Customer', tracking=True)
    original_value = fields.Monetary(required=True, tracking=True)
    revised_value = fields.Monetary(required=True, tracking=True)
    reason = fields.Text(required=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], default='draft', tracking=True, copy=False)
    requested_by = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)
    approved_by = fields.Many2one('res.users', readonly=True, copy=False)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('combine001.tax.adjustment') or 'New'
        return super().create(vals_list)

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                continue
            rec.state = 'pending'
            rec.message_post(body=_(
                "Adjustment requested by %(user)s: %(old)s -> %(new)s. Reason: %(reason)s",
                user=rec.requested_by.name, old=rec.original_value,
                new=rec.revised_value, reason=rec.reason,
            ))

    def action_approve(self):
        for rec in self:
            if not self.env.user.has_group('account.group_account_manager'):
                raise UserError(_('Only a Finance Manager can approve a Tax Ledger adjustment.'))
            if rec.state != 'pending':
                raise UserError(_('Only a Pending Approval adjustment can be approved.'))
            rec.write({'state': 'approved', 'approved_by': self.env.user.id})
            rec.message_post(body=_('Approved by %s.', self.env.user.name))

    def action_reject(self):
        for rec in self:
            if not self.env.user.has_group('account.group_account_manager'):
                raise UserError(_('Only a Finance Manager can reject a Tax Ledger adjustment.'))
            if rec.state != 'pending':
                raise UserError(_('Only a Pending Approval adjustment can be rejected.'))
            rec.write({'state': 'rejected', 'approved_by': self.env.user.id})
            rec.message_post(body=_('Rejected by %s.', self.env.user.name))
