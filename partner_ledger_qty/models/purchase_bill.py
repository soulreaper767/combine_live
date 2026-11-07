from odoo import _, models
from odoo.exceptions import UserError


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def action_create_invoice(self, attachment_ids=False):
        """Create Bill without uploading a file. Guides instead of making an
        empty bill: nothing received yet -> explains; a draft bill already
        waiting -> opens it rather than creating a duplicate."""
        if not attachment_ids and len(self) == 1:
            order = self
            lines = order.order_line.filtered(lambda l: not l.display_type and l.product_id)
            billable = any(not l.product_uom_id.is_zero(l.qty_to_invoice) for l in lines)
            if not billable:
                drafts = order.invoice_ids.filtered(lambda m: m.state == 'draft')
                if drafts:
                    return order.action_view_invoice(drafts)
                detail = '\n'.join('- %s: ordered %s, received %s, billed %s %s' % (
                    l.product_id.display_name, l.product_qty, l.qty_received, l.qty_invoiced, l.product_uom_id.name) for l in lines)
                raise UserError('\n\n'.join([
                    _('%s: there is nothing to bill yet.', order.name),
                    detail,
                    _('A bill follows the quantity received. What to do:\n'
                      '1. Receive the goods first (Stores: Gate Pass Inward > Inspection > GRN, or the order\'s Receipt).\n'
                      '2. Then click "Create Bill" again - the bill takes the received quantity at the order rate.'),
                    _('Paying the vendor before the goods arrive? Record it as a payment with "Advance" ticked '
                      '(Accounting > Vendors > Payments) and apply it to the bill later.'),
                ]))
        return super().action_create_invoice(attachment_ids=attachment_ids)
