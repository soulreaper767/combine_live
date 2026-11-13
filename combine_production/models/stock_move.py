from collections import defaultdict

from odoo import fields, models


class StockMove(models.Model):
    _inherit = 'stock.move'

    x_fifo_allocation_ids = fields.One2many('combine.fifo.allocation', 'out_move_id', string='FIFO Cost Split')

    def _set_value(self, correction_quantity=None):
        """Record the FIFO split of outgoing FIFO moves, computed from the very stack
        `super()._set_value` is about to use (mirrors its loop and fifo_qty_already_processed)."""
        splits = {}
        if not correction_quantity:
            processed = defaultdict(float)
            for company, moves in self.grouped('company_id').items():
                for move in moves:
                    move = move.with_company(company.id)
                    if move.is_in:
                        continue
                    if not move._is_out() or move.product_id.lot_valuated or move.product_id.cost_method != 'fifo':
                        continue
                    qty = move._get_valued_qty()
                    product = move.product_id.with_context(fifo_qty_already_processed=processed[move.product_id])
                    splits[move.id] = product._combine_fifo_breakdown(qty)
                    processed[move.product_id] += qty
        old_values = {m.id: m.value for m in self} if correction_quantity else {}
        res = super()._set_value(correction_quantity=correction_quantity)
        Alloc = self.env['combine.fifo.allocation'].sudo()
        if splits:
            Alloc.search([('out_move_id', 'in', list(splits))]).unlink()
            vals = []
            for move_id, pieces in splits.items():
                for seq, (in_move, qty, value, beyond) in enumerate(pieces):
                    vals.append({'out_move_id': move_id, 'in_move_id': in_move.id or False, 'sequence': seq,
                                 'quantity': qty, 'value': value, 'unit_cost': value / qty if qty else 0.0,
                                 'beyond_stock': beyond})
            Alloc.create(vals)
        elif correction_quantity:
            # quantity of a done delivery changed: Odoo scales the value, scale the split the same way
            for move in self.filtered('x_fifo_allocation_ids'):
                old = old_values.get(move.id)
                if old:
                    ratio = move.value / old
                    for line in move.sudo().x_fifo_allocation_ids:
                        line.write({'quantity': line.quantity * ratio, 'value': line.value * ratio})
        return res

    def action_view_fifo_split(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': self.env._('FIFO cost - %s', self.reference or self.product_id.display_name),
            'res_model': 'combine.fifo.allocation', 'view_mode': 'list',
            'domain': [('out_move_id', '=', self.id)],
        }


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    x_fifo_allocation_count = fields.Integer(compute='_compute_x_fifo_allocation_count')

    def _compute_x_fifo_allocation_count(self):
        groups = dict(self.env['combine.fifo.allocation'].sudo()._read_group(
            [('picking_id', 'in', self.ids)], ['picking_id'], ['__count']))
        for picking in self:
            picking.x_fifo_allocation_count = groups.get(picking, 0)

    def action_view_fifo_cost(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': self.env._('FIFO cost - %s', self.name),
            'res_model': 'combine.fifo.allocation', 'view_mode': 'list',
            'domain': [('picking_id', '=', self.id)],
        }
