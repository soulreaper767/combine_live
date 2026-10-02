from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PurchaseAmendment(models.Model):
    """Controlled RFQ/PO amendment workflow (BRD for Purchase Module
    Changes sec. 5.2: "Changes should only be possible through an
    authorized amendment/revision process"). Direct mirror of
    combine001.sale.amendment - a confirmed PO's price/quantity is
    locked (see purchase_order.PurchaseOrderLine.write); the only way to
    change it is: draft an amendment here, submit it, have a Purchase
    Manager approve it, then Apply it - which writes the new price/qty
    straight onto the SAME existing purchase.order.line record (never
    creates a new one for an existing product), so there is no
    possibility of duplicate lines. Every apply is chatter-logged with
    user/date and old->new values for the audit trail the BRD asks for.
    """
    _name = 'combine001.purchase.amendment'
    _description = 'Purchase Order Amendment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(default='New', copy=False, readonly=True)
    purchase_order_id = fields.Many2one('purchase.order', required=True, ondelete='cascade',
                                         string='RFQ / Purchase Order', tracking=True)
    partner_id = fields.Many2one(related='purchase_order_id.partner_id', store=True, string='Vendor')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('applied', 'Applied'),
    ], default='draft', copy=False, tracking=True)
    reason = fields.Text(required=True, tracking=True)
    line_ids = fields.One2many('combine001.purchase.amendment.line', 'amendment_id', string='Amendment Lines')
    requested_by = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)
    approved_by = fields.Many2one('res.users', readonly=True, copy=False)
    applied_date = fields.Datetime(readonly=True, copy=False)
    currency_id = fields.Many2one(related='purchase_order_id.currency_id')
    company_id = fields.Many2one(related='purchase_order_id.company_id', store=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('combine001.purchase.amendment') or 'New'
        return super().create(vals_list)

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                continue
            if not rec.line_ids:
                raise UserError(_('Add at least one amendment line before submitting.'))
            if rec.purchase_order_id.state != 'purchase':
                raise UserError(_('Only a confirmed Purchase Order can be amended.'))
            rec.state = 'pending'
            rec.message_post(body=_(
                "Amendment submitted by %(user)s. Reason: %(reason)s",
                user=rec.requested_by.name, reason=rec.reason,
            ))

    def action_approve(self):
        for rec in self:
            if not self.env.user.has_group('purchase.group_purchase_manager'):
                raise UserError(_('Only a Purchase Manager can approve a PO amendment.'))
            if rec.state != 'pending':
                raise UserError(_('Only a Pending Approval amendment can be approved.'))
            rec.write({'state': 'approved', 'approved_by': self.env.user.id})
            rec.message_post(body=_('Approved by %s.', self.env.user.name))

    def action_reject(self):
        for rec in self:
            if not self.env.user.has_group('purchase.group_purchase_manager'):
                raise UserError(_('Only a Purchase Manager can reject a PO amendment.'))
            if rec.state != 'pending':
                raise UserError(_('Only a Pending Approval amendment can be rejected.'))
            rec.write({'state': 'rejected', 'approved_by': self.env.user.id})
            rec.message_post(body=_('Rejected by %s.', self.env.user.name))

    def action_apply(self):
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_('Only an Approved amendment can be applied.'))
            rec.line_ids._apply()
            rec.write({'state': 'applied', 'applied_date': fields.Datetime.now()})
            rec.message_post(body=_('Amendment applied by %s.', self.env.user.name))


class PurchaseAmendmentLine(models.Model):
    _name = 'combine001.purchase.amendment.line'
    _description = 'Purchase Order Amendment Line'

    amendment_id = fields.Many2one('combine001.purchase.amendment', required=True, ondelete='cascade')
    purchase_order_id = fields.Many2one(related='amendment_id.purchase_order_id', store=True)
    order_line_id = fields.Many2one(
        'purchase.order.line', string='Existing Line',
        domain="[('order_id', '=', purchase_order_id), ('display_type', '=', False)]",
        help='Leave empty to add a brand new product line via this amendment. '
             'Set this to revise an existing line - reapplying always updates '
             'that same line, it never creates a duplicate.')
    product_id = fields.Many2one('product.product', string='Product')
    old_price_unit = fields.Float(readonly=True, copy=False)
    new_price_unit = fields.Float(string='New Price')
    old_qty = fields.Float(readonly=True, copy=False)
    new_qty = fields.Float(string='New Quantity')

    @api.onchange('order_line_id')
    def _onchange_order_line_id(self):
        if self.order_line_id:
            self.product_id = self.order_line_id.product_id
            self.old_price_unit = self.order_line_id.price_unit
            self.old_qty = self.order_line_id.product_qty
            self.new_price_unit = self.order_line_id.price_unit
            self.new_qty = self.order_line_id.product_qty

    def _apply(self):
        PurchaseOrderLine = self.env['purchase.order.line'].with_context(combine001_amendment_apply=True)
        for line in self:
            if line.order_line_id:
                vals = {}
                if line.new_price_unit and line.new_price_unit != line.order_line_id.price_unit:
                    vals['price_unit'] = line.new_price_unit
                if line.new_qty and line.new_qty != line.order_line_id.product_qty:
                    vals['product_qty'] = line.new_qty
                if vals:
                    line.order_line_id.with_context(combine001_amendment_apply=True).write(vals)
                    line.purchase_order_id.message_post(body=_(
                        "PO amendment %(amendment)s: %(product)s price/qty "
                        "updated from %(old_price)s / %(old_qty)s to "
                        "%(new_price)s / %(new_qty)s.",
                        amendment=line.amendment_id.name, product=line.order_line_id.product_id.display_name,
                        old_price=line.old_price_unit, old_qty=line.old_qty,
                        new_price=line.order_line_id.price_unit, new_qty=line.order_line_id.product_qty,
                    ))
            elif line.product_id:
                new_line = PurchaseOrderLine.create({
                    'order_id': line.purchase_order_id.id,
                    'product_id': line.product_id.id,
                    'product_qty': line.new_qty or 1.0,
                    'price_unit': line.new_price_unit or line.product_id.standard_price,
                })
                line.order_line_id = new_line.id
                line.purchase_order_id.message_post(body=_(
                    "PO amendment %(amendment)s: added new line %(product)s "
                    "(qty %(qty)s @ %(price)s).",
                    amendment=line.amendment_id.name, product=line.product_id.display_name,
                    qty=new_line.product_qty, price=new_line.price_unit,
                ))
