from collections import defaultdict

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .stores_print import num


class GoodsReceiptNote(models.Model):
    _name = 'combine.grn'
    _description = 'Goods Receipt Note'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'combine.stores.print.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(default=lambda self: _('New'), readonly=True, copy=False)
    gate_pass_id = fields.Many2one('combine.gate.pass.in', string='Gate Pass Inward', required=True, ondelete='restrict')
    inspection_id = fields.Many2one('combine.inspection', string='Inspection', ondelete='restrict')
    partner_id = fields.Many2one(related='gate_pass_id.partner_id', store=True, string='Party')
    purchase_id = fields.Many2one(related='gate_pass_id.purchase_id', store=True)
    date = fields.Date(default=fields.Date.context_today, required=True)
    user_id = fields.Many2one('res.users', string='Received By', default=lambda self: self.env.user)
    picking_ids = fields.Many2many('stock.picking', string='Receipts', readonly=True, copy=False)
    state = fields.Selection([('draft', 'Draft'), ('done', 'Received'), ('cancel', 'Cancelled')],
                             default='draft', required=True, tracking=True, copy=False)
    line_ids = fields.One2many('combine.grn.line', 'grn_id', string='Items')
    note = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('combine.grn') or _('New')
        return super().create(vals_list)

    def action_validate(self):
        for grn in self:
            if grn.state != 'draft':
                continue
            if not grn.line_ids.filtered(lambda l: l.qty > 0):
                raise UserError(_('Nothing to receive on %s.', grn.name))
            cancel_rest = grn.inspection_id.rejection_action == 'cancel'
            pickings = grn._receive_purchase_lines(cancel_rest) | grn._receive_other_lines()
            grn.write({'state': 'done', 'picking_ids': [Command.set(pickings.ids)]})
            grn.gate_pass_id.state = 'done'
        return True

    def _validate_picking(self, picking, no_backorder):
        if 'x_approval_state' in picking._fields:
            # quality inspection and GRN are this receipt's approval
            picking.x_approval_state = 'approved'
        ctx = {'skip_backorder': True, 'skip_sms': True}
        if no_backorder:
            ctx['picking_ids_not_to_backorder'] = picking.ids
        res = picking.with_context(**ctx).button_validate()
        if isinstance(res, dict) and res.get('res_model'):
            raise UserError(_('Receipt %s needs attention before it can be validated (%s).', picking.name, res.get('name')))

    def _receive_purchase_lines(self, cancel_rest):
        """Accepted quantities go in through the purchase order's own open receipt."""
        lines = self.line_ids.filtered(lambda l: l.purchase_line_id and l.qty > 0)
        if not lines:
            return self.env['stock.picking']
        todo = defaultdict(float)
        for line in lines:
            todo[line.purchase_line_id] += line.uom_id._compute_quantity(line.qty, line.purchase_line_id.product_uom_id)
        orders = lines.purchase_line_id.order_id
        pickings = orders.picking_ids.filtered(lambda p: p.picking_type_code == 'incoming' and p.state not in ('done', 'cancel'))
        if not pickings:
            raise UserError(_('%s has no open receipt left to receive into.', ', '.join(orders.mapped('name'))))
        for picking in pickings:
            for move in picking.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
                want = todo.get(move.purchase_line_id, 0.0)
                qty = move.purchase_line_id.product_uom_id._compute_quantity(want, move.product_uom) if want else 0.0
                qty = min(qty, move.product_uom_qty) if move.product_uom_qty else qty
                move.quantity = qty
                move.picked = True
                if move.purchase_line_id in todo:
                    todo[move.purchase_line_id] -= move.product_uom._compute_quantity(qty, move.purchase_line_id.product_uom_id)
        left = {pol: q for pol, q in todo.items() if q > 0.0001}
        if left:
            raise UserError(_('Accepted quantity exceeds what is still due on the purchase order for: %s',
                              ', '.join(pol.product_id.display_name for pol in left)))
        done = self.env['stock.picking']
        for picking in pickings.filtered(lambda p: any(m.quantity for m in p.move_ids)):
            self._validate_picking(picking, cancel_rest)
            done |= picking
        return done

    def _receive_other_lines(self):
        """Items that arrived without a purchase order: a plain receipt from the party."""
        lines = self.line_ids.filtered(lambda l: not l.purchase_line_id and l.qty > 0)
        if not lines:
            return self.env['stock.picking']
        ptype = self.env['stock.picking.type'].search([('code', '=', 'incoming'), ('company_id', '=', self.gate_pass_id.company_id.id)], limit=1)
        picking = self.env['stock.picking'].create({
            'picking_type_id': ptype.id,
            'partner_id': self.partner_id.id,
            'origin': f'{self.name} / {self.gate_pass_id.name}',
            'location_id': ptype.default_location_src_id.id or self.env.ref('stock.stock_location_suppliers').id,
            'location_dest_id': ptype.default_location_dest_id.id,
            'move_ids': [Command.create({
                'product_id': l.product_id.id, 'product_uom_qty': l.qty, 'product_uom': l.uom_id.id,
                'location_id': ptype.default_location_src_id.id or self.env.ref('stock.stock_location_suppliers').id,
                'location_dest_id': ptype.default_location_dest_id.id,
            }) for l in lines],
        })
        picking.action_confirm()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        self._validate_picking(picking, True)
        return picking

    def action_view_receipts(self):
        return self.gate_pass_id._open(self.picking_ids, _('Receipts'))

    # print
    def _print_title(self):
        return 'Goods Receipt Note'

    def _print_info(self):
        return [('GRN No.', self.name), ('Date', self._print_date(self.date)), ('Gate Pass', self.gate_pass_id.name),
                ('Inspection', self.inspection_id.name or '-'), ('Purchase Order', self.purchase_id.name or '-'),
                ('Party Inv / DC', self.gate_pass_id.party_ref or '-')]

    def _print_party(self):
        return self.partner_id

    def _print_columns(self):
        return [('Sr.', 'c'), ('Item', ''), ('Qty Received', 'n'), ('UoM', 'c'), ('Net Wt.', 'n'), ('Remarks', '')]

    def _print_rows(self):
        return [[i, l.product_id.display_name, num(l.qty), l.uom_id.name, num(l.net_weight), l.note or '']
                for i, l in enumerate(self.line_ids, 1)]

    def _print_totals(self):
        return {2: num(sum(self.line_ids.mapped('qty'))), 4: num(sum(self.line_ids.mapped('net_weight')))}

    def _print_signatures(self):
        return ['Received by (Store)', 'Quality Inspector', 'Approved by']


class GoodsReceiptNoteLine(models.Model):
    _name = 'combine.grn.line'
    _description = 'Goods Receipt Note Line'

    grn_id = fields.Many2one('combine.grn', required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one('product.product', string='Item', required=True)
    purchase_line_id = fields.Many2one('purchase.order.line', string='PO Line')
    uom_id = fields.Many2one('uom.uom', string='UoM', required=True)
    qty = fields.Float(string='Qty Received', digits='Product Unit')
    net_weight = fields.Float(string='Net Wt.', digits='Stock Weight')
    note = fields.Char(string='Remarks')
