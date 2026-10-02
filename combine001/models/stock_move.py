from odoo import _, fields, models
from odoo.exceptions import UserError


class StockMove(models.Model):
    _inherit = 'stock.move'

    x_contract_price = fields.Float(
        related='sale_line_id.price_unit', store=True, string='Contract Price',
        help='Read-only, mirrored from the Contract/Sales Order line (BRD sec. 7.4).')

    def _action_done(self, cancel_backorder=False):
        for move in self:
            sale_line = move.sale_line_id
            if sale_line and move.picking_type_id.code == 'outgoing' and move.quantity:
                already_done = sum(sale_line.move_ids.filtered(
                    lambda m: m.state == 'done' and m.id != move.id
                ).mapped('quantity'))
                new_total = already_done + move.quantity
                if new_total > sale_line.product_uom_qty:
                    raise UserError(_(
                        "Cumulative delivered quantity for %(product)s "
                        "(%(done)s) would exceed the Sales Order quantity "
                        "(%(ordered)s) on order %(order)s.",
                        product=sale_line.product_id.display_name,
                        done=new_total, ordered=sale_line.product_uom_qty,
                        order=sale_line.order_id.name,
                    ))
        return super()._action_done(cancel_backorder=cancel_backorder)

    def write(self, vals):
        """BRD for Purchase Module Changes sec. 5.3: the approved
        purchase quantity (the Receipt's own "Demand" - product_uom_qty)
        must not be alterable once the RFQ is confirmed - only the
        ACTUAL physically-received quantity (`quantity`) may differ from
        it, which is exactly how Odoo already models a short/excess/
        partial receipt (backorders), so that field is intentionally
        left untouched here."""
        if 'product_uom_qty' in vals and not self.env.context.get('combine001_amendment_apply'):
            for move in self:
                if move.purchase_line_id and move.purchase_line_id.order_id.state == 'purchase':
                    raise UserError(_(
                        "%(product)s: this quantity is locked because the related RFQ has been "
                        "confirmed. Please use the approved amendment process to make changes.",
                        product=move.product_id.display_name,
                    ))
        return super().write(vals)
