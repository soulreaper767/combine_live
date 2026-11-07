"""Clear guidance instead of bare "Invalid Operation" errors on the purchase
flow: what happened, why, and exactly what to do next (with a button to
the right screen where there is one). The rules themselves are unchanged."""
from odoo import _, fields, models
from odoo.exceptions import RedirectWarning, UserError


def _people(env, group_xmlid):
    group = env.ref(group_xmlid, raise_if_not_found=False)
    if not group:
        return ''
    users = env['res.users'].sudo().search([('group_ids', 'in', group.ids), ('share', '=', False), ('active', '=', True)], limit=6) \
        if 'group_ids' in env['res.users']._fields else group.sudo().users.filtered(lambda u: not u.share)[:6]
    users = users.filtered(lambda u: u.id not in (1,) and u.login not in ('__system__', 'public'))
    return ', '.join(users.mapped('name')) or _('a user with the "%s" right', group.display_name)


def _approval_help(rec, doc_label, action_label, group_xmlid, where):
    state = rec.x_approval_state
    approvers = _people(rec.env, group_xmlid)
    name = rec.name if rec.name and rec.name != '/' else _('(draft, %s)', rec.partner_id.name or '-')
    head = _('%(doc)s %(name)s cannot be %(action)s yet.', doc=doc_label, name=name, action=action_label)
    if state == 'submitted':
        when = fields.Datetime.context_timestamp(rec, rec.x_submitted_date).strftime('%d-%b-%y %H:%M') if rec.x_submitted_date else ''
        return '\n\n'.join([
            head,
            _('It is waiting for approval (submitted by %(by)s %(when)s).', by=rec.x_submitted_by.name or '-', when=when),
            _('What to do: ask %(who)s to open it (%(where)s) and click "Approve". Then %(action)s it again.',
              who=approvers, where=where, action=action_label.replace('validated', 'validate').replace('posted', 'post')),
        ])
    if state == 'rejected':
        return '\n\n'.join([
            head,
            _('It was rejected by %(by)s. Reason: %(why)s', by=rec.x_rejected_by.name or '-', why=rec.x_rejection_reason or '-'),
            _('What to do: click "Reset to Draft", correct it, click "Submit for Approval", and have %s approve it.', approvers),
        ])
    return '\n\n'.join([
        head,
        _('Purchase %s need approval before this step.', doc_label.lower() + 's'),
        _('What to do:\n1. On this document click "Submit for Approval".\n2. %(who)s opens it (%(where)s) and clicks "Approve".\n'
          '3. Then %(action)s it.', who=approvers, where=where,
          action=action_label.replace('validated', 'validate').replace('posted', 'post')),
    ])


def _amendment_warning(env, product, what):
    action = env.ref('combine001.action_purchase_amendment', raise_if_not_found=False)
    msg = '\n\n'.join([
        _('%(item)s: %(what)s is fixed once the purchase order is confirmed.', item=product.display_name, what=what),
        _('This keeps the order, receipts and bills consistent with what was approved.'),
        _('What to do to change it:\n1. Purchase > PO Amendments > New.\n2. Choose the purchase order, enter the new quantity / price and the reason.\n'
          '3. Click "Submit"; a Purchase Manager approves it.\n4. Click "Apply" - the order, its open receipt and bill follow.'),
    ])
    if action:
        return RedirectWarning(msg, action.id, _('Open PO Amendments'))
    return UserError(msg)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _combine001_check_approved(self, action_label):
        for rec in self:
            if rec.x_approval_state != 'approved':
                raise UserError(_approval_help(rec, _('Receipt'), action_label, 'purchase.group_purchase_manager',
                                               _('Inventory > Receipts')) + '\n\n' +
                                _('Tip: receiving through Stores (Gate Pass Inward > Inspection > GRN) approves the receipt '
                                  'with the GRN, no separate approval needed.'))
        return super()._combine001_check_approved(action_label)


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _combine001_check_approved(self, action_label):
        for rec in self:
            if rec.x_approval_state != 'approved':
                label = _('Debit Note') if rec.move_type == 'in_refund' else _('Vendor Bill')
                raise UserError(_approval_help(rec, label, action_label, 'account.group_account_manager',
                                               _('Accounting > Vendors > Bills')))
        return super()._combine001_check_approved(action_label)


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def action_create_invoice(self, attachment_ids=False):
        # bills / debit notes made by the system from the order are not manual price edits;
        # attachment_ids: "Upload Bill" passes the uploaded vendor bill file(s)
        return super(PurchaseOrder, self.with_context(combine001_amendment_apply=True)).action_create_invoice(attachment_ids=attachment_ids)


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    def write(self, vals):
        if ({'price_unit', 'product_qty', 'product_id'} & set(vals)) and not self.env.context.get('combine001_amendment_apply'):
            for line in self:
                if not line.display_type and line.order_id.state == 'purchase':
                    what = _('the price') if 'price_unit' in vals and 'product_qty' not in vals else _('the quantity / price')
                    raise _amendment_warning(self.env, line.product_id, what)
        return super().write(vals)


class StockMove(models.Model):
    _inherit = 'stock.move'

    def write(self, vals):
        if 'product_uom_qty' in vals and not self.env.context.get('combine001_amendment_apply'):
            for move in self:
                if move.purchase_line_id and move.purchase_line_id.order_id.state == 'purchase' \
                        and move.product_uom.compare(vals['product_uom_qty'], move.product_uom_qty) != 0:
                    msg = _amendment_warning(self.env, move.product_id, _('the ordered quantity ("Demand") on its receipt'))
                    msg.args = (msg.args[0] + '\n\n' + _('Receiving less or more than ordered does not need an amendment: '
                                                         'enter the quantity actually received in "Quantity" and validate - '
                                                         'Odoo keeps the rest as a back order.'),) + msg.args[1:]
                    raise msg
        return super().write(vals)


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    def write(self, vals):
        if ('price_unit' in vals or 'quantity' in vals) and not self.env.context.get('combine001_amendment_apply'):
            for line in self:
                if line.move_id.state == 'draft' and line.purchase_line_id and line.move_id.move_type in ('in_invoice', 'in_refund') \
                        and ((('price_unit' in vals) and line.currency_id.compare_amounts(vals['price_unit'], line.price_unit) != 0)
                             or (('quantity' in vals) and line.product_uom_id.compare(vals['quantity'], line.quantity) != 0)):
                    msg = _amendment_warning(self.env, line.product_id, _('the rate'))
                    msg.args = ('\n\n'.join([
                        _('%s: the quantity and rate of this bill line come from the purchase order and what was received.',
                          line.product_id.display_name),
                        _('Quantity: the bill takes the quantity received (GRN). If the vendor billed a different quantity, receive / return '
                          'the difference first (GRN, or return to vendor) and then use "Create Bill" on the purchase order again.'),
                        _('Rate: change it with a PO Amendment (Purchase > PO Amendments), then create the bill again.'),
                    ]),) + msg.args[1:]
                    raise msg
        return super().write(vals)
