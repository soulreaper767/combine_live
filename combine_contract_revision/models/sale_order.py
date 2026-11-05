from markupsafe import Markup

from odoo import Command, _, fields, models
from odoo.exceptions import UserError

# lets the documents of a revision through combine001's price / quantity locks
REVISION_CTX = {'combine001_amendment_apply': True, 'combine_contract_revision': True}


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    x_revision_count = fields.Integer(string='Revisions', copy=False, readonly=True)
    x_revision_open = fields.Boolean(string='Under Revision', copy=False, readonly=True,
                                     help='Reopened by Revise Contract: its deliveries and invoices are in draft '
                                          'and follow the contract when it is confirmed again.')

    # ------------------------------------------------------------------ revise
    def action_revise_contract(self):
        for order in self:
            order._revise_contract()
        return True

    def _revise_contract(self):
        """Put the contract, its deliveries and its invoices back to draft -
        the same documents, same numbers - with every stock and accounting
        effect removed, so they can be corrected and submitted again."""
        self.ensure_one()
        if self.state != 'sale':
            raise UserError(_('Only a confirmed contract can be revised.'))
        invoices = self.invoice_ids.filtered(lambda m: m.state != 'cancel' and m.move_type == 'out_invoice')
        paid = invoices.filtered(lambda m: m.payment_state not in ('not_paid', 'invoicing_legacy'))
        if paid:
            raise UserError(_(
                'Revise %(order)s: these invoices have payments registered - reverse or unreconcile the payments first:\n%(inv)s',
                order=self.name, inv='\n'.join(paid.mapped('name'))))
        if self.invoice_ids.filtered(lambda m: m.move_type == 'out_refund' and m.state == 'posted'):
            raise UserError(_('Revise %s: a credit note is posted against this contract; reverse it first.', self.name))
        deliveries = self.picking_ids.filtered(lambda p: p.state != 'cancel')
        returns = deliveries.filtered(lambda p: p.state == 'done' and p.picking_type_code == 'incoming')
        if returns:
            raise UserError(_('Revise %(order)s: goods were already returned against it (%(ret)s); '
                              'the revision cannot reopen those deliveries.', order=self.name, ret=', '.join(returns.mapped('name'))))
        log = []
        # 1. invoices: back to draft, same number; extras raised on posting removed
        for inv in invoices:
            if inv.state == 'posted':
                inv._revision_undo_extras()
                inv.button_draft()
                log.append(_('Invoice %s reset to draft', inv.name))
            inv.x_revision_open = True
        # 2. deliveries: the same documents back to draft, stock put back
        for picking in deliveries.filtered(lambda p: p.picking_type_code == 'outgoing'):
            was_done = picking.state == 'done'
            picking._revision_reset_to_draft()
            log.append(_('Delivery %(name)s reset to draft%(how)s', name=picking.name,
                         how=_(' (stock put back)') if was_done else ''))
        # 3. contract back to draft - without Odoo's cancel, which would cancel the documents above
        if self.locked:
            self.action_unlock()
        self.write({'state': 'draft', 'x_revision_open': True, 'x_revision_count': self.x_revision_count + 1})
        self.message_post(body=Markup('<p><b>%s</b></p><ul>%s</ul>') % (
            _('Contract revised (revision %s): back to draft with its deliveries and invoices, no stock or ledger effect left. '
              'Make the changes and confirm it again.', self.x_revision_count),
            Markup('').join(Markup('<li>%s</li>') % line for line in log) or Markup('<li>%s</li>') % _('nothing delivered or invoiced')))

    # ------------------------------------------------------------------ resubmit
    def action_confirm(self):
        revised = self.filtered('x_revision_open')
        for order in revised:
            order._revision_sync_deliveries()
        reopened = {order.id: order.picking_ids.filtered('x_revision_open') for order in revised}
        res = super().action_confirm()
        for order in revised:
            pickings = reopened[order.id].filtered(lambda p: p.state != 'cancel')
            pickings.filtered(lambda p: p.state == 'draft').action_confirm()
            to_assign = pickings.filtered(lambda p: p.state in ('confirmed', 'waiting'))
            if to_assign:
                to_assign.action_assign()
            order.picking_ids.filtered('x_revision_open').write({'x_revision_open': False})
            order._revision_sync_invoices()
            order.x_revision_open = False
            order.message_post(body=_('Revised contract confirmed: deliveries %(dl)s ready, draft invoices %(inv)s follow the new rates.',
                                      dl=', '.join(pickings.mapped('name')) or '-',
                                      inv=', '.join(order.invoice_ids.filtered(lambda m: m.state == 'draft').mapped('name')) or '-'))
        return res

    def _revision_sync_deliveries(self):
        """The reopened delivery lines take the contract's (new) quantities;
        lines removed from the contract are dropped. New contract lines get
        their delivery from Odoo when the contract is confirmed."""
        self.ensure_one()
        pickings = self.picking_ids.filtered(lambda p: p.x_revision_open and p.state == 'draft')
        for move in pickings.move_ids.filtered(lambda m: m.state == 'draft'):
            line = move.sale_line_id
            if not line or line.order_id != self or line.product_id != move.product_id or not line.product_uom_qty:
                move.with_context(**REVISION_CTX)._action_cancel()
                continue
            done_elsewhere = sum(m.product_uom._compute_quantity(m.quantity, line.product_uom_id)
                                 for m in line.move_ids if m.state == 'done' and m.picking_code == 'outgoing')
            qty = line.product_uom_id._compute_quantity(max(line.product_uom_qty - done_elsewhere, 0.0), move.product_uom)
            if move.product_uom.is_zero(qty):
                move.with_context(**REVISION_CTX)._action_cancel()
            elif move.product_uom.compare(qty, move.product_uom_qty):
                move.with_context(**REVISION_CTX).product_uom_qty = qty

    def _revision_sync_invoices(self):
        """Draft invoices of the revision follow the contract: rate, discount
        and taxes; quantity capped to the contract. Lines of removed contract
        lines are dropped."""
        self.ensure_one()
        for inv in self.invoice_ids.filtered(lambda m: m.state == 'draft' and m.x_revision_open):
            commands = []
            for aml in inv.invoice_line_ids.filtered(lambda l: l.display_type == 'product'):
                line = aml.sale_line_ids[:1]
                if not line:
                    if aml.x_revision_sale_line_id:
                        commands.append(Command.delete(aml.id))
                    continue
                vals = {'price_unit': line.price_unit, 'discount': line.discount, 'tax_ids': [Command.set(line.tax_ids.ids)]}
                cap = line.product_uom_id._compute_quantity(line.product_uom_qty, aml.product_uom_id or line.product_uom_id)
                if aml.quantity > cap:
                    vals['quantity'] = cap
                commands.append(Command.update(aml.id, vals))
            if commands:
                inv.with_context(**REVISION_CTX).write({'invoice_line_ids': commands})
            inv.x_revision_open = False


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def unlink(self):
        # remember the invoice lines of a contract line removed during a revision, to drop them on resubmit
        for line in self.filtered(lambda l: l.order_id.x_revision_open):
            line.invoice_lines.filtered(lambda a: a.move_id.state == 'draft').write({'x_revision_sale_line_id': line.id})
        return super().unlink()


class AccountMove(models.Model):
    _inherit = 'account.move'

    x_revision_open = fields.Boolean(copy=False, readonly=True)

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


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    x_revision_sale_line_id = fields.Integer(copy=False, readonly=True)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    x_revision_open = fields.Boolean(copy=False, readonly=True)

    def _revision_reset_to_draft(self):
        """The same delivery back to draft. A validated one is undone through
        Odoo's own edit of done quantities (quants restored, the move's value
        back to zero); a stock journal entry, if the setup made one, is
        cancelled. Number, lines and links stay; nothing new is created."""
        self.ensure_one()
        picking = self.with_context(**REVISION_CTX)
        done = picking.move_ids.filtered(lambda m: m.state == 'done')
        if done:
            entries = done.account_move_id if 'account_move_id' in done._fields else self.env['account.move']
            done.move_line_ids.write({'quantity': 0.0})
            done.write({'state': 'draft', 'picked': False})
            done.move_line_ids.unlink()
            if 'value' in done._fields:
                done.write({'value': 0.0})
            for entry in entries.filtered(lambda e: e.state != 'cancel'):
                if entry.state == 'posted':
                    entry.button_draft()
                entry.button_cancel()
            if entries:
                done.write({'account_move_id': False})
            if 'analytic_account_line_ids' in done._fields and done.analytic_account_line_ids:
                done.analytic_account_line_ids.sudo().unlink()
        open_moves = picking.move_ids.filtered(lambda m: m.state not in ('draft', 'done', 'cancel'))
        if open_moves:
            open_moves._do_unreserve()
            open_moves.write({'state': 'draft', 'picked': False})
        picking.write({'date_done': False, 'x_revision_open': True})
        if picking.state != 'draft':
            raise UserError(_('%(name)s could not be reset to draft (state: %(state)s).', name=picking.name, state=picking.state))
        return True
