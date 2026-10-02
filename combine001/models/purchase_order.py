from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .commission_agent import COMMISSION_BASE_SELECTION

COMMISSION_BASIS_SELECTION = [
    ('po_value', 'Purchase Order Value'),
    ('received_value', 'Received Value'),
    ('invoice_value', 'Vendor Invoice Value'),
    ('paid_value', 'Paid Invoice Value'),
]


class PurchaseOrder(models.Model):
    """BRD for Purchase Module Changes sec. 4-6: RFQ and PO are the same
    document (a purchase.order in draft/sent state is the "RFQ", the
    same record confirmed is the "PO") - same reasoning already applied
    to Contract/Delivery Order on the sales side.

    Approval gate: rather than layering a second, custom approval state
    on top of this record (see combine001_approval_mixin.py's own
    docstring for why that mixin is deliberately NOT used here), this
    reuses Odoo's own native "double validation" mechanism
    (`company.po_double_validation`) - forced on unconditionally for
    every RFQ regardless of amount (see res_company.py), so
    `button_confirm()` always routes through the native 'to approve'
    state, and only `purchase.group_purchase_manager` can call
    `button_approve()` to actually confirm it into a PO. Reinforced here
    with an explicit Python-level group check (the native button is only
    guarded by view-level `groups=`, which a technical user could bypass
    via RPC) and a few audit fields native Odoo doesn't track
    (`x_approved_by`, rejection reason - `date_approve` already exists
    natively).
    """
    _inherit = 'purchase.order'

    x_approved_by = fields.Many2one('res.users', readonly=True, copy=False, string='Approved By')
    x_rejection_reason = fields.Text(copy=False, string='Rejection Reason')
    x_amendment_ids = fields.One2many('combine001.purchase.amendment', 'purchase_order_id', string='PO Amendments')
    x_amendment_count = fields.Integer(compute='_compute_x_amendment_count')

    commission_agent_id = fields.Many2one('combine001.commission.agent', string='Commission Agent', tracking=True)
    commission_rate = fields.Float(string='Commission Rate (%)')
    commission_base = fields.Selection(COMMISSION_BASE_SELECTION, string='Commission Base')
    commission_basis = fields.Selection(
        COMMISSION_BASIS_SELECTION, string='Commission Basis', default='invoice_value',
        help='What the commission percentage is applied against: the PO\'s own value, the value '
             'actually received so far, the vendor invoice value, or the value actually paid to '
             'the vendor so far (recomputes live as payments are made).')

    def _compute_x_amendment_count(self):
        counts = dict(self.env['combine001.purchase.amendment']._read_group(
            [('purchase_order_id', 'in', self.ids)], ['purchase_order_id'], ['__count'],
        ))
        for order in self:
            order.x_amendment_count = counts.get(order, 0)

    @api.onchange('commission_agent_id')
    def _onchange_combine001_commission_agent_id(self):
        if self.commission_agent_id:
            self.commission_rate = self.commission_agent_id.default_rate
            self.commission_base = self.commission_agent_id.default_base

    def button_approve(self, force=False):
        for order in self:
            if order.state in ('draft', 'to approve') and not self.env.user.has_group('purchase.group_purchase_manager'):
                raise UserError(_('Only a Purchase Manager can approve/confirm this RFQ.'))
        to_approve = self.filtered(lambda o: o.state in ('draft', 'sent', 'to approve'))
        res = super().button_approve(force=force)
        to_approve.filtered(lambda o: o.state == 'purchase').write({'x_approved_by': self.env.user.id})
        return res

    def action_combine001_reject(self):
        for order in self:
            if not self.env.user.has_group('purchase.group_purchase_manager'):
                raise UserError(_('Only a Purchase Manager can reject this RFQ.'))
            if order.state != 'to approve':
                raise UserError(_('Only an RFQ waiting for approval can be rejected.'))
            order.button_draft()
            order.message_post(body=_(
                "Rejected by %(user)s. Reason: %(reason)s",
                user=self.env.user.name, reason=order.x_rejection_reason or '-',
            ))

    def action_view_x_amendments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('PO Amendments'),
            'res_model': 'combine001.purchase.amendment',
            'view_mode': 'list,form',
            'domain': [('purchase_order_id', '=', self.id)],
            'context': {'default_purchase_order_id': self.id},
        }


class PurchaseOrderLine(models.Model):
    """BRD sec. 5.1/5.2: once an RFQ is confirmed (state == 'purchase'),
    product/quantity/price are locked - a direct mirror of the Contract
    price lock on the sales side (sale_order.py), same amendment-only
    escape hatch."""
    _inherit = 'purchase.order.line'

    def write(self, vals):
        if ({'price_unit', 'product_qty', 'product_id'} & set(vals)) and not self.env.context.get('combine001_amendment_apply'):
            for line in self:
                if line.display_type:
                    continue
                if line.order_id.state == 'purchase':
                    raise UserError(_(
                        "%(product)s: this price/quantity is locked because the related RFQ "
                        "has been confirmed. Please use the approved amendment process "
                        "(Combine001 > Purchase > PO Amendments) to make changes.",
                        product=line.product_id.display_name,
                    ))
        return super().write(vals)
