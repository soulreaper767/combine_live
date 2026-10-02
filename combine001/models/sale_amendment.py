from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SaleAmendment(models.Model):
    """Controlled Contract amendment workflow (BRD sec. 3.3 / 12).

    A confirmed Contract's price/quantity is locked (see
    sale_order.SaleOrderLine.write). The only way to change it is: draft
    an amendment here, submit it, have a Sales Manager approve it, then
    Apply it - which writes the new price/qty straight onto the SAME
    existing sale.order.line records (never creates new ones for an
    existing product), so there is no possibility of duplicate lines, and
    also re-baselines x_quoted_price/x_quoted_qty so the normal SO-005/
    SO-006 "can't exceed quotation" guard keeps working against the new
    baseline afterward. Also pushes the revised price onto any
    not-yet-posted Sales Invoice lines already raised against the
    affected order lines (BRD sec. 9/12). Every apply is chatter-logged
    with user/date and old->new values for
    the audit trail the BRD asks for.
    """
    _name = 'combine001.sale.amendment'
    _description = 'Contract Amendment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(default='New', copy=False, readonly=True)
    sale_order_id = fields.Many2one('sale.order', required=True, ondelete='cascade',
                                     string='Contract / Sales Order', tracking=True)
    partner_id = fields.Many2one(related='sale_order_id.partner_id', store=True, string='Customer')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('applied', 'Applied'),
    ], default='draft', copy=False, tracking=True)
    reason = fields.Text(required=True, tracking=True)
    line_ids = fields.One2many('combine001.sale.amendment.line', 'amendment_id', string='Amendment Lines')
    requested_by = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)
    approved_by = fields.Many2one('res.users', readonly=True, copy=False)
    applied_date = fields.Datetime(readonly=True, copy=False)
    currency_id = fields.Many2one(related='sale_order_id.currency_id')
    company_id = fields.Many2one(related='sale_order_id.company_id', store=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('combine001.sale.amendment') or 'New'
        return super().create(vals_list)

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                continue
            if not rec.line_ids:
                raise UserError(_('Add at least one amendment line before submitting.'))
            if rec.sale_order_id.state != 'sale':
                raise UserError(_('Only a confirmed Contract/Sales Order can be amended.'))
            rec.state = 'pending'
            rec.message_post(body=_(
                "Amendment submitted by %(user)s. Reason: %(reason)s",
                user=rec.requested_by.name, reason=rec.reason,
            ))

    def action_approve(self):
        for rec in self:
            if not self.env.user.has_group('sales_team.group_sale_manager'):
                raise UserError(_('Only a Sales Manager can approve a Contract amendment.'))
            if rec.state != 'pending':
                raise UserError(_('Only a Pending Approval amendment can be approved.'))
            rec.write({'state': 'approved', 'approved_by': self.env.user.id})
            rec.message_post(body=_('Approved by %s.', self.env.user.name))

    def action_reject(self):
        for rec in self:
            if not self.env.user.has_group('sales_team.group_sale_manager'):
                raise UserError(_('Only a Sales Manager can reject a Contract amendment.'))
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


class SaleAmendmentLine(models.Model):
    _name = 'combine001.sale.amendment.line'
    _description = 'Contract Amendment Line'

    amendment_id = fields.Many2one('combine001.sale.amendment', required=True, ondelete='cascade')
    sale_order_id = fields.Many2one(related='amendment_id.sale_order_id', store=True)
    order_line_id = fields.Many2one(
        'sale.order.line', string='Existing Line',
        domain="[('order_id', '=', sale_order_id), ('display_type', '=', False)]",
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
            self.old_qty = self.order_line_id.product_uom_qty
            self.new_price_unit = self.order_line_id.price_unit
            self.new_qty = self.order_line_id.product_uom_qty

    def _apply(self):
        SaleOrderLine = self.env['sale.order.line'].with_context(combine001_amendment_apply=True)
        for line in self:
            if line.order_line_id:
                vals = {}
                if line.new_price_unit and line.new_price_unit != line.order_line_id.price_unit:
                    vals['price_unit'] = line.new_price_unit
                    vals['x_quoted_price'] = line.new_price_unit
                if line.new_qty and line.new_qty != line.order_line_id.product_uom_qty:
                    vals['product_uom_qty'] = line.new_qty
                    vals['x_quoted_qty'] = line.new_qty
                if vals:
                    line.order_line_id.with_context(combine001_amendment_apply=True).write(vals)
                    line.sale_order_id.message_post(body=_(
                        "Contract amendment %(amendment)s: %(product)s price/qty "
                        "updated from %(old_price)s / %(old_qty)s to "
                        "%(new_price)s / %(new_qty)s.",
                        amendment=line.amendment_id.name, product=line.order_line_id.product_id.display_name,
                        old_price=line.old_price_unit, old_qty=line.old_qty,
                        new_price=line.order_line_id.price_unit, new_qty=line.order_line_id.product_uom_qty,
                    ))
                    line._combine001_sync_draft_invoice_lines()
            elif line.product_id:
                new_line = SaleOrderLine.create({
                    'order_id': line.sale_order_id.id,
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.new_qty or 1.0,
                    'price_unit': line.new_price_unit or line.product_id.list_price,
                })
                new_line.x_quoted_qty = new_line.product_uom_qty
                new_line.x_quoted_price = new_line.price_unit
                line.order_line_id = new_line.id
                line.sale_order_id.message_post(body=_(
                    "Contract amendment %(amendment)s: added new line %(product)s "
                    "(qty %(qty)s @ %(price)s).",
                    amendment=line.amendment_id.name, product=line.product_id.display_name,
                    qty=new_line.product_uom_qty, price=new_line.price_unit,
                ))

    def _combine001_sync_draft_invoice_lines(self):
        """Push the revised price onto any not-yet-posted invoice lines
        already raised against this order line (BRD sec. 9: 'applicable
        invoice information shall be updated'). Posted invoices are real
        financial records and are intentionally left untouched - a
        posted invoice is corrected the normal accounting way (credit
        note), not silently rewritten."""
        self.ensure_one()
        draft_lines = self.order_line_id.invoice_lines.filtered(lambda l: l.move_id.state == 'draft')
        if draft_lines:
            draft_lines.with_context(combine001_amendment_apply=True).write({
                'price_unit': self.order_line_id.price_unit,
                'quantity': self.order_line_id.product_uom_qty,
            })
