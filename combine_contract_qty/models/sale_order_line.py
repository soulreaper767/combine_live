from markupsafe import Markup, escape

from odoo import _, models
from odoo.exceptions import UserError

AMEND_CTX = {'combine001_amendment_apply': True, 'combine_contract_qty': True}


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    # ------------------------------------------------------------ helpers
    def _cq_amendable(self):
        """Product lines of a confirmed contract, or of one reopened by Revise Contract."""
        return self.filtered(lambda l: l.product_id and not l.display_type and not l.x_is_charge_line
                             and (l.order_id.state == 'sale' or l.order_id.x_revision_open))

    def _cq_delivered_qty(self):
        self.ensure_one()
        return self.qty_delivered

    def _cq_invoiced_qty(self):
        """Posted invoices less posted credit notes, in the line's unit."""
        self.ensure_one()
        qty = 0.0
        for aml in self.invoice_lines.filtered(lambda a: a.move_id.state == 'posted'):
            q = aml.product_uom_id._compute_quantity(aml.quantity, self.product_uom_id) if aml.product_uom_id else aml.quantity
            qty += -q if aml.move_id.move_type == 'out_refund' else q
        return qty

    def _cq_check_new_qty(self, new_qty):
        uom = self.product_uom_id
        delivered = self._cq_delivered_qty()
        if uom.compare(new_qty, delivered) < 0:
            raise UserError(_(
                "%(order)s - %(product)s: the quantity cannot go down to %(new)s because %(done)s %(uom)s "
                "has already been delivered.\n\nReturn the extra quantity on the delivery first "
                "(Delivery > Return), then reduce the contract.",
                order=self.order_id.name, product=self.product_id.display_name,
                new=new_qty, done=delivered, uom=uom.name))
        invoiced = self._cq_invoiced_qty()
        if uom.compare(new_qty, invoiced) < 0:
            raise UserError(_(
                "%(order)s - %(product)s: the quantity cannot go down to %(new)s because %(inv)s %(uom)s "
                "has already been invoiced.\n\nIssue a credit note for the extra quantity first "
                "(Invoice > Credit Note), then reduce the contract.",
                order=self.order_id.name, product=self.product_id.display_name,
                new=new_qty, inv=invoiced, uom=uom.name))

    # ------------------------------------------------------------ write
    def write(self, vals):
        if 'product_uom_qty' not in vals or self.env.context.get('combine001_amendment_apply'):
            return super().write(vals)
        amend = self._cq_amendable()
        if not amend:
            return super().write(vals)
        new_qty = vals['product_uom_qty']
        old = {}
        for line in amend:
            if line.order_id.state == 'sale' and 'price_unit' in vals \
                    and line.currency_id.compare_amounts(vals['price_unit'], line.price_unit):
                raise UserError(_(
                    "%(product)s: the rate on a confirmed Contract cannot be changed directly. "
                    "Use a Contract Amendment (Combine001 > Contract Amendments) or Revise Contract instead.",
                    product=line.product_id.display_name))
            if line.product_uom_id.compare(new_qty, line.product_uom_qty):
                line._cq_check_new_qty(new_qty)
            old[line.id] = (line.product_uom_qty, line.price_unit)

        others = self - amend
        res = super(SaleOrderLine, others).write(vals) if others else True
        # the new quantity is the new baseline: combine001's "not above the quoted qty" check and the
        # delivery / invoice limits (which read product_uom_qty) follow it
        amend_vals = dict(vals, x_quoted_qty=new_qty)
        super(SaleOrderLine, amend.with_context(**AMEND_CTX)).write(amend_vals)

        for line in amend:
            old_qty, old_price = old[line.id]
            # a confirmed contract keeps its rate when only the quantity changes
            if line.order_id.state == 'sale' and 'price_unit' not in vals \
                    and line.currency_id.compare_amounts(line.price_unit, old_price):
                super(SaleOrderLine, line.with_context(**AMEND_CTX)).write({'price_unit': old_price})
            if line.product_uom_id.compare(old_qty, line.product_uom_qty):
                line._cq_notify(old_qty)
        return res

    def _cq_notify(self, old_qty):
        self.ensure_one()
        order = self.order_id
        uom = self.product_uom_id.name or ''
        text = _("Contract quantity amended: %(product)s %(old)s -> %(new)s %(uom)s by %(user)s. "
                 "Delivery and invoice limits are now %(new)s %(uom)s.",
                 product=self.product_id.display_name, old=old_qty, new=self.product_uom_qty,
                 uom=uom, user=self.env.user.name)
        draft_over = self.invoice_lines.filtered(
            lambda a: a.move_id.state == 'draft' and a.move_id.move_type == 'out_invoice'
            and self.product_uom_id.compare(a.quantity, self.product_uom_qty) > 0)
        if draft_over:
            text += ' ' + _("Draft invoice(s) %(inv)s carry more than the new quantity - correct them before posting.",
                            inv=', '.join(draft_over.move_id.mapped(lambda m: m.name or _('(draft)'))))
        order.message_post(body=Markup('<b>%s</b>') % escape(text))
        self.env.user._bus_send('simple_notification', {
            'type': 'warning', 'title': _('Contract %s amended', order.name), 'message': text, 'sticky': False})
