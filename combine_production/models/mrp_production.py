from odoo import _, api, fields, models
from odoo.exceptions import UserError


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    x_unit_cost = fields.Float(string='Unit Cost', digits='Product Price', copy=False, tracking=True,
                               help='Cost per unit of the item produced. The production is valued at '
                                    'quantity x unit cost and the cost is saved on the item.')
    x_production_value = fields.Monetary(string='Production Value', compute='_compute_x_production_value',
                                         currency_field='x_currency_id')
    x_currency_id = fields.Many2one('res.currency', related='company_id.currency_id')
    x_unit_id = fields.Many2one('stock.warehouse', related='picking_type_id.warehouse_id', string='Production Unit',
                                store=True)

    @api.depends('x_unit_cost', 'qty_producing', 'qty_produced', 'product_qty', 'state',
                 'move_finished_ids.value', 'move_finished_ids.state')
    def _compute_x_production_value(self):
        for mo in self:
            done = mo.move_finished_ids.filtered(lambda m: m.state == 'done' and m.product_id == mo.product_id)
            if done:
                mo.x_production_value = sum(done.mapped('value'))
            else:
                qty = mo.qty_producing or mo.product_qty
                mo.x_production_value = qty * mo.x_unit_cost

    def _cal_price(self, consumed_moves):
        """The unit cost entered wins: finished goods are valued at quantity x unit cost."""
        res = super()._cal_price(consumed_moves)
        for mo in self.filtered('x_unit_cost'):
            finished = mo.move_finished_ids.filtered(
                lambda m: m.product_id == mo.product_id and m.state not in ('done', 'cancel')
                and m.product_uom.compare(m.quantity, 0) > 0)
            for move in finished:
                # price_unit is per product UoM; unit cost is per the order's UoM
                factor = move.product_uom._compute_quantity(1.0, move.product_id.uom_id) or 1.0
                move.price_unit = mo.x_unit_cost / factor
        return res

    def _get_backorder_mo_vals(self):
        res = super()._get_backorder_mo_vals()
        res['x_unit_cost'] = self.x_unit_cost
        return res

    def _combine_needs_unit_cost(self):
        self.ensure_one()
        return self.product_id.cost_method in ('fifo', 'average') and not self.x_unit_cost

    def button_mark_done(self):
        missing = self.filtered(lambda mo: mo._combine_needs_unit_cost())
        if missing:
            raise UserError(_('Enter the Unit Cost of the production on %s before marking it done.',
                              ', '.join(missing.mapped('name'))))
        res = super().button_mark_done()
        # backorders created on the way are in self.procurement_group_id; only the done ones count
        self.filtered(lambda m: m.state == 'done')._combine_save_production_cost()
        return res

    def _combine_save_production_cost(self):
        """The unit cost becomes the item's Last Production Cost (latest production date wins)."""
        for mo in self.filtered('x_unit_cost').sorted(lambda m: (m.date_finished or fields.Datetime.now(), m.id)):
            tmpl = mo.product_id.product_tmpl_id.sudo()
            date = (mo.date_finished or fields.Datetime.now()).date()
            if not tmpl.x_production_cost_date or date >= tmpl.x_production_cost_date:
                tmpl.write({'x_production_cost': mo.x_unit_cost, 'x_production_cost_date': date,
                            'x_production_cost_mo_id': mo.id})
