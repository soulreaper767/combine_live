from collections import defaultdict

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    x_challan_invoice_ids = fields.One2many('account.move', 'x_delivery_challan_id', string='Challan Invoices')
    x_challan_invoice_count = fields.Integer(compute='_compute_x_challan_invoice_count')

    @api.depends('x_challan_invoice_ids.state')
    def _compute_x_challan_invoice_count(self):
        for picking in self:
            picking.x_challan_invoice_count = len(
                picking.x_challan_invoice_ids.filtered(lambda m: m.state != 'cancel'))

    def action_challan_invoice(self):
        """Create a draft customer invoice for exactly this challan's
        delivered quantities, built from the Contract lines' own invoice
        values (price, discount, taxes, accounts) - only the quantity
        comes from the challan."""
        self.ensure_one()
        if self.picking_type_code != 'outgoing' or self.state != 'done' or not self.sale_id:
            raise UserError(_('Only a validated Delivery Challan linked to a Contract can be invoiced.'))
        existing = self.x_challan_invoice_ids.filtered(lambda m: m.state != 'cancel')
        if existing:
            return self._challan_invoice_action(existing[:1])

        delivered = defaultdict(float)
        for move in self.move_ids.filtered(lambda m: m.state == 'done' and m.sale_line_id):
            line = move.sale_line_id
            delivered[line] += move.product_uom._compute_quantity(move.quantity, line.product_uom_id)

        order = self.sale_id.with_company(self.sale_id.company_id)
        line_cmds = []
        for line in order.order_line.filtered(lambda l: l in delivered):
            rounding = line.product_uom_id.rounding
            qty = min(delivered[line], line.qty_delivered - line.qty_invoiced)
            if float_compare(qty, 0.0, precision_rounding=rounding) <= 0:
                continue
            for vals in line._prepare_invoice_lines_vals_list(quantity=qty, sequence=line.sequence):
                line_cmds.append(Command.create(vals))
        if not line_cmds:
            raise UserError(_('Nothing left to invoice on %s: its quantities are already invoiced.', self.name))

        invoice_vals = order._prepare_invoice()
        invoice_vals['invoice_line_ids'] = line_cmds
        invoice_vals['x_delivery_challan_id'] = self.id
        invoice_vals['ref'] = ', '.join(filter(None, [invoice_vals.get('ref'), self.name]))
        invoice = self.env['account.move'].with_company(order.company_id).with_context(
            default_move_type='out_invoice').create(invoice_vals)
        return self._challan_invoice_action(invoice)

    def action_view_challan_invoices(self):
        self.ensure_one()
        return self._challan_invoice_action(self.x_challan_invoice_ids.filtered(lambda m: m.state != 'cancel'))

    def _challan_invoice_action(self, invoices):
        action = {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'name': _('Invoices'),
            'context': {'default_move_type': 'out_invoice'},
        }
        if len(invoices) == 1:
            action.update(view_mode='form', res_id=invoices.id)
        else:
            action.update(view_mode='list,form', domain=[('id', 'in', invoices.ids)])
        return action
