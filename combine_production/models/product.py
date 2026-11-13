import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ProductCategory(models.Model):
    _inherit = 'product.category'

    @api.model
    def _combine_production_set_fifo(self):
        """Install only: Finished Goods / Yarn -> FIFO (raw materials keep their costing)."""
        cats = self.search([('name', '=', 'Yarn'), ('parent_id.name', '=', 'Finished Goods')])
        for company in self.env['res.company'].search([]):
            todo = cats.with_company(company).filtered(lambda c: c.property_cost_method != 'fifo')
            if todo:
                todo.write({'property_cost_method': 'fifo'})
                _logger.info('combine_production: %s set to FIFO for %s', todo.mapped('complete_name'), company.name)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    x_production_cost = fields.Float(string='Last Production Cost', digits='Product Price', copy=False, readonly=True,
                                     help='Unit cost of the latest production entered for this item.')
    x_production_cost_date = fields.Date(string='Last Production Date', copy=False, readonly=True)
    x_production_cost_mo_id = fields.Many2one('mrp.production', string='Last Production Order', copy=False, readonly=True)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def _combine_fifo_breakdown(self, quantity):
        """Same walk as stock_account's `_run_fifo` (same stack, same context), but returns the pieces:
        [(in_move, qty, value, beyond_stock)]."""
        self.ensure_one()
        pieces = []
        if self.uom_id.compare(quantity, 0) <= 0:
            return pieces
        stack, qty_on_first_move = self._run_fifo_get_stack()
        last_move = False
        while quantity > 0 and stack:
            move = stack.pop(0)
            last_move = move
            if qty_on_first_move:
                valued_qty = move._get_valued_qty()
                in_qty = qty_on_first_move
                in_value = move.value * in_qty / valued_qty if valued_qty else 0.0
                qty_on_first_move = 0
            else:
                in_qty = move._get_valued_qty()
                in_value = move.value
            if in_qty > quantity:
                in_value = in_value * quantity / in_qty
                in_qty = quantity
            if in_qty:
                pieces.append((move, in_qty, in_value, False))
            quantity -= in_qty
        if quantity > 0:
            rate = (last_move.value / last_move.quantity) if last_move and last_move.quantity else self.standard_price
            pieces.append((last_move or self.env['stock.move'], quantity, quantity * rate, True))
        return pieces
