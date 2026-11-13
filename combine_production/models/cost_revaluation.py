"""Cost revaluation of zero-cost stock: gives a unit cost to stock that came in at 0 and to what was
already delivered / consumed from it, with the accounting effect for real-time valued items."""
from odoo import _, api, fields, models


class CostRevaluation(models.Model):
    _name = 'combine.cost.revaluation'
    _description = 'Cost revaluation'
    _order = 'id desc'

    name = fields.Char(required=True, readonly=True, default='/', copy=False)
    date = fields.Datetime(default=fields.Datetime.now, readonly=True)
    accounting_date = fields.Date(readonly=True)
    user_id = fields.Many2one('res.users', default=lambda s: s.env.user, readonly=True)
    company_id = fields.Many2one('res.company', default=lambda s: s.env.company, required=True, readonly=True)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')
    note = fields.Text()
    line_ids = fields.One2many('combine.cost.revaluation.line', 'revaluation_id', string='Items')
    move_ids = fields.One2many('combine.cost.revaluation.move', 'revaluation_id', string='Stock Moves Changed')
    stock_delta = fields.Monetary(compute='_compute_totals', string='Stock Value Added')
    consumption_delta = fields.Monetary(compute='_compute_totals', string='Consumption / COGS Added')
    account_move_ids = fields.Many2many('account.move', compute='_compute_totals', string='Journal Entries')
    journal_entry_id = fields.Many2one('account.move', string='Revaluation Entry', readonly=True)

    @api.depends('move_ids.delta', 'move_ids.kind', 'move_ids.account_move_id', 'journal_entry_id')
    def _compute_totals(self):
        for rec in self:
            rec.stock_delta = sum(rec.move_ids.filtered(lambda m: m.kind == 'stock_in').mapped('delta'))
            rec.consumption_delta = sum(rec.move_ids.filtered(lambda m: m.kind != 'stock_in').mapped('delta'))
            rec.account_move_ids = rec.move_ids.account_move_id | rec.journal_entry_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('combine.cost.revaluation') or '/'
        return super().create(vals_list)

    def action_view_entries(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Journal Entries'), 'res_model': 'account.move',
                'view_mode': 'list,form', 'domain': [('id', 'in', self.account_move_ids.ids)]}


class CostRevaluationLine(models.Model):
    _name = 'combine.cost.revaluation.line'
    _description = 'Cost revaluation - item'

    revaluation_id = fields.Many2one('combine.cost.revaluation', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True, string='Item')
    new_cost = fields.Float(string='New Unit Cost', digits='Product Price')
    stock_qty = fields.Float(string='Zero-cost Qty Received', digits='Product Unit')
    consumed_qty = fields.Float(string='Zero-cost Qty Delivered / Consumed', digits='Product Unit')
    currency_id = fields.Many2one('res.currency', related='revaluation_id.currency_id')
    stock_delta = fields.Monetary(string='Stock Value Added')
    consumption_delta = fields.Monetary(string='Consumption Added')


class CostRevaluationMove(models.Model):
    _name = 'combine.cost.revaluation.move'
    _description = 'Cost revaluation - stock move changed'

    revaluation_id = fields.Many2one('combine.cost.revaluation', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Item')
    stock_move_id = fields.Many2one('stock.move', string='Stock Move', ondelete='set null')
    reference = fields.Char()
    kind = fields.Selection([('stock_in', 'Stock received at 0'), ('consumption_batch', 'Delivered / consumed (FIFO batch)'),
                             ('consumption_flat', 'Delivered / consumed (no batch record)')], required=True)
    quantity = fields.Float(digits='Product Unit')
    old_value = fields.Monetary()
    new_value = fields.Monetary()
    delta = fields.Monetary()
    currency_id = fields.Many2one('res.currency', related='revaluation_id.currency_id')
    account_move_id = fields.Many2one('account.move', string='Journal Entry')
