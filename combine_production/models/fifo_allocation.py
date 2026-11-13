from odoo import _, api, fields, models


class FifoAllocation(models.Model):
    """Which incoming stock (production / receipt / opening) an outgoing move consumed under FIFO.

    Written when the outgoing move is valued, with exactly the stack Odoo used,
    so the lines of one delivery add up to the delivery's cost."""
    _name = 'combine.fifo.allocation'
    _description = 'FIFO cost allocation'
    _order = 'date desc, out_move_id, sequence, id'

    out_move_id = fields.Many2one('stock.move', string='Outgoing Move', required=True, index=True, ondelete='cascade')
    in_move_id = fields.Many2one('stock.move', string='Taken From', index=True, ondelete='set null')
    sequence = fields.Integer()
    company_id = fields.Many2one('res.company', related='out_move_id.company_id', store=True)
    product_id = fields.Many2one('product.product', related='out_move_id.product_id', store=True, string='Item')
    picking_id = fields.Many2one('stock.picking', related='out_move_id.picking_id', store=True, string='Delivery')
    partner_id = fields.Many2one('res.partner', related='out_move_id.picking_id.partner_id', store=True, string='Customer')
    date = fields.Datetime(related='out_move_id.date', store=True)
    quantity = fields.Float(string='Quantity', digits='Product Unit')
    unit_cost = fields.Float(string='Rate', digits='Product Price')
    value = fields.Monetary(string='Cost', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')
    beyond_stock = fields.Boolean(help='More was delivered than was in stock: valued at the last known rate.')
    source_production_id = fields.Many2one('mrp.production', related='in_move_id.production_id', store=True,
                                           string='Production')
    source_label = fields.Char(string='Source', compute='_compute_source_label')
    source_date = fields.Datetime(related='in_move_id.date', string='Source Date')

    @api.depends('in_move_id', 'beyond_stock')
    def _compute_source_label(self):
        for rec in self:
            rec.source_label = rec._source_label()

    def _source_label(self):
        self.ensure_one()
        move = self.in_move_id
        label = ''
        if move.production_id:
            label = move.production_id.name
        elif move.picking_id:
            label = move.picking_id.name
        elif move:
            label = move.reference or _('Inventory adjustment')
        if self.beyond_stock:
            label = _('%s (beyond stock)', label) if label else _('Beyond stock')
        return label or _('Opening / unknown')
