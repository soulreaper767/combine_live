from odoo import _, fields, models
from odoo.exceptions import UserError


class Combine001ApprovalMixin(models.AbstractModel):
    """Generic Draft -> Submitted -> Approved -> (Done/Posted) workflow
    with an explicit Rejected -> Draft path, for documents that have no
    native Odoo approval gate of their own (BRD for Purchase Module
    Changes sec. 7/8: Purchase Receipt and Vendor Bill). Each inheriting
    model supplies its own `_combine001_approval_group()` (the
    res.groups external id authorized to approve/reject) and calls
    `_combine001_check_approved()` from its own validate/post override
    to actually enforce the gate - this mixin only manages the state
    machine and its audit trail, it doesn't touch the underlying
    document's own workflow at all.

    Purchase Order itself does NOT use this mixin - it already has a
    near-identical native mechanism (`company.po_double_validation` +
    `button_approve()` / `purchase.group_purchase_manager`), extended
    in place instead (see models/purchase_order.py) rather than
    layering a second, redundant approval state on top of Odoo's own.
    """
    _name = 'combine001.approval.mixin'
    _description = 'Combine001 Approval Mixin'

    x_approval_state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], default='draft', copy=False, tracking=True, string='Approval Status')
    x_submitted_by = fields.Many2one('res.users', readonly=True, copy=False, string='Submitted By')
    x_submitted_date = fields.Datetime(readonly=True, copy=False, string='Submitted On')
    x_approved_by = fields.Many2one('res.users', readonly=True, copy=False, string='Approved By')
    x_approved_date = fields.Datetime(readonly=True, copy=False, string='Approved On')
    x_rejected_by = fields.Many2one('res.users', readonly=True, copy=False, string='Rejected By')
    x_rejected_date = fields.Datetime(readonly=True, copy=False, string='Rejected On')
    x_rejection_reason = fields.Text(copy=False, string='Rejection Reason')

    def _combine001_approval_group(self):
        """Return the res.groups external id authorized to approve/
        reject this document. Must be overridden by every inheriting
        model."""
        raise NotImplementedError

    def action_combine001_submit(self):
        for rec in self:
            if rec.x_approval_state != 'draft':
                continue
            rec.write({
                'x_approval_state': 'submitted',
                'x_submitted_by': self.env.user.id,
                'x_submitted_date': fields.Datetime.now(),
            })
            rec.message_post(body=_('Submitted for approval by %s.', self.env.user.name))

    def action_combine001_approve(self):
        for rec in self:
            if not self.env.user.has_group(rec._combine001_approval_group()):
                raise UserError(_('You are not authorized to approve this document.'))
            if rec.x_approval_state != 'submitted':
                raise UserError(_('Only a Submitted document can be approved.'))
            rec.write({
                'x_approval_state': 'approved',
                'x_approved_by': self.env.user.id,
                'x_approved_date': fields.Datetime.now(),
            })
            rec.message_post(body=_('Approved by %s.', self.env.user.name))

    def action_combine001_reject(self):
        for rec in self:
            if not self.env.user.has_group(rec._combine001_approval_group()):
                raise UserError(_('You are not authorized to reject this document.'))
            if rec.x_approval_state != 'submitted':
                raise UserError(_('Only a Submitted document can be rejected.'))
            rec.write({
                'x_approval_state': 'rejected',
                'x_rejected_by': self.env.user.id,
                'x_rejected_date': fields.Datetime.now(),
            })
            rec.message_post(body=_(
                'Rejected by %(user)s. Reason: %(reason)s',
                user=self.env.user.name, reason=rec.x_rejection_reason or '-',
            ))

    def action_combine001_reset_draft(self):
        for rec in self:
            if rec.x_approval_state != 'rejected':
                continue
            rec.write({'x_approval_state': 'draft', 'x_rejection_reason': False})
            rec.message_post(body=_('Reset to Draft by %s.', self.env.user.name))

    def _combine001_check_approved(self, action_label):
        for rec in self:
            if rec.x_approval_state != 'approved':
                raise UserError(_(
                    "%(doc)s cannot be %(action)s until its approval workflow is "
                    "complete (currently: %(state)s). Submit it and have an "
                    "authorized approver approve it first.",
                    doc=rec.display_name, action=action_label,
                    state=dict(rec._fields['x_approval_state'].selection).get(rec.x_approval_state),
                ))
