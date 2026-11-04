from markupsafe import Markup

from odoo import _, fields, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    x_revision_count = fields.Integer(string='Revisions', copy=False, readonly=True)

    def action_revise_contract(self):
        for order in self:
            order._revise_contract()
        return True

    def _revise_contract(self):
        self.ensure_one()
        if self.state != 'sale':
            raise UserError(_('Only a confirmed contract can be revised.'))
        invoices = self.invoice_ids.filtered(lambda m: m.state != 'cancel')
        paid = invoices.filtered(lambda m: m.payment_state not in ('not_paid', 'invoicing_legacy'))
        if paid:
            raise UserError(_(
                'Revise %(order)s: these invoices have payments registered - reverse or unreconcile the payments first:\n%(inv)s',
                order=self.name, inv='\n'.join(paid.mapped('name'))))
        log = []
        # 1. invoices: back to draft, then cancelled (numbers kept)
        for inv in invoices:
            was = inv.state
            inv._revision_undo_extras()
            if inv.state == 'posted':
                inv.button_draft()
            inv.button_cancel()
            log.append(_('Invoice %(name)s (%(was)s) cancelled', name=inv.name, was=was))
        # 2. deliveries: validated ones returned in full, open ones cancelled
        for picking in self.picking_ids.filtered(lambda p: p.state == 'done' and p.picking_type_code == 'outgoing'):
            returned = picking._revision_return_all()
            if returned:
                log.append(_('Delivery %(name)s returned by %(ret)s', name=picking.name, ret=returned.name))
        if self.locked:
            self.action_unlock()
        self._action_cancel()
        self.action_draft()
        self.x_revision_count += 1
        self.message_post(body=Markup('<p><b>%s</b></p><ul>%s</ul>') % (
            _('Contract revised (revision %s): all impacts reversed, back to draft for changes.', self.x_revision_count),
            Markup('').join(Markup('<li>%s</li>') % line for line in log) or Markup('<li>%s</li>') % _('nothing delivered or invoiced')))


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _revision_undo_extras(self):
        """Side records some customizations create when an invoice is posted."""
        self.ensure_one()
        if 'combine001.commission.line' in self.env:
            lines = self.env['combine001.commission.line'].sudo().search([('invoice_id', '=', self.id)])
            if lines.filtered(lambda l: l.payment_state == 'paid'):
                raise UserError(_('%s has commission already paid to the agent; reverse that first.', self.name))
            lines.unlink()
        if 'combine001.gst.saving.line' in self.env:
            for saving in self.env['combine001.gst.saving.line'].sudo().search([('move_id', '=', self.id)]):
                entry = saving.journal_entry_id
                saving.unlink()
                if entry.state == 'posted':
                    entry.button_draft()
                entry.button_cancel()


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _revision_return_all(self):
        """Return whatever of this delivery has not been returned yet and validate it."""
        self.ensure_one()
        wizard = self.env['stock.return.picking'].with_context(
            active_id=self.id, active_ids=self.ids, active_model='stock.picking').create({})
        for line in wizard.product_return_moves:
            move = line.move_id
            qty = move.quantity - sum(m.quantity for m in move.move_dest_ids
                                      if m.origin_returned_move_id == move and m.state != 'cancel')
            line.quantity = move.product_uom.round(qty) if qty > 0 else 0.0
        if not any(line.quantity > 0 for line in wizard.product_return_moves):
            return self.browse()
        returned = wizard._create_return()
        returned.action_confirm()
        returned.action_assign()
        for move in returned.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        returned._action_done()
        return returned
