from odoo import _, fields, models
from odoo.exceptions import UserError


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    x_demand_line_id = fields.Many2one('combine.demand.note.line', string='Demand Line', index='btree_not_null', copy=False)


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    x_gate_pass_in_ids = fields.One2many('combine.gate.pass.in', 'purchase_id', string='Gate Passes Inward')
    x_gate_pass_in_count = fields.Integer(compute='_compute_x_stores_counts')
    x_demand_note_count = fields.Integer(compute='_compute_x_stores_counts')

    def _compute_x_stores_counts(self):
        for order in self:
            order.x_gate_pass_in_count = len(order.x_gate_pass_in_ids)
            order.x_demand_note_count = len(order.order_line.x_demand_line_id.demand_id)

    def action_gate_in(self):
        self.ensure_one()
        if self.state not in ('purchase', 'done'):
            raise UserError(_('Confirm the purchase order first.'))
        GatePass = self.env['combine.gate.pass.in']
        gp = GatePass.create({'partner_id': self.partner_id.id, 'purchase_id': self.id,
                              'line_ids': [(0, 0, vals) for vals in GatePass._lines_from_purchase(self)]})
        return {'type': 'ir.actions.act_window', 'res_model': gp._name, 'res_id': gp.id, 'view_mode': 'form'}

    def action_view_gate_in(self):
        return self.env['combine.gate.pass.in']._open(self.x_gate_pass_in_ids, _('Gate Passes Inward'))

    def action_view_demand_notes(self):
        notes = self.order_line.x_demand_line_id.demand_id
        return self.env['combine.gate.pass.in']._open(notes, _('Demand Notes'))


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    x_gate_pass_out_ids = fields.One2many('combine.gate.pass.out', 'picking_id', string='Gate Passes Outward')
    x_gate_pass_out_count = fields.Integer(compute='_compute_x_gate_pass_out_count')

    def _compute_x_gate_pass_out_count(self):
        for picking in self:
            picking.x_gate_pass_out_count = len(picking.x_gate_pass_out_ids)

    def action_gate_out(self):
        self.ensure_one()
        if self.picking_type_code != 'outgoing' or self.state != 'done':
            raise UserError(_('A Gate Pass Outward is made from a validated delivery.'))
        GatePass = self.env['combine.gate.pass.out']
        gp = GatePass.create(GatePass._values_from_delivery(self))
        return {'type': 'ir.actions.act_window', 'res_model': gp._name, 'res_id': gp.id, 'view_mode': 'form'}

    def action_view_gate_out(self):
        return self.env['combine.gate.pass.in']._open(self.x_gate_pass_out_ids, _('Gate Passes Outward'))


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _split(self, qty, restrict_partner_id=False):
        """Odoo's own backorder split of a partial receipt rewrites the move's
        demand. combine001 locks that demand on confirmed purchase orders
        (against manual changes) and so blocked every partial receipt with a
        backorder - which combine001 itself means to allow. The split is
        system-made, so it is let through; manual edits stay locked."""
        return super(StockMove, self.with_context(combine001_amendment_apply=True))._split(
            qty, restrict_partner_id=restrict_partner_id)
