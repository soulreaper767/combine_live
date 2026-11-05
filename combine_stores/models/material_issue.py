from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare

from .stores_print import num


class ProductionDepartment(models.Model):
    """A production department that consumes material (Blow Room, Carding,
    Ring Spinning, Winding, ...). Each has its own consumption location, so
    stock issued to it leaves the warehouse at its cost."""
    _name = 'combine.production.department'
    _description = 'Production Department'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    code = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    manager_id = fields.Many2one('res.users', string='Department Head')
    location_id = fields.Many2one('stock.location', string='Consumption Location', readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        departments = super().create(vals_list)
        for dept in departments:
            parent = self.env.ref('stock.stock_location_locations_virtual', raise_if_not_found=False)
            dept.location_id = self.env['stock.location'].sudo().create({
                'name': dept.name, 'usage': 'production', 'company_id': dept.company_id.id,
                'location_id': parent.id if parent else False,
            })
        return departments

    def write(self, vals):
        res = super().write(vals)
        if 'name' in vals:
            for dept in self.filtered('location_id'):
                dept.location_id.sudo().name = dept.name
        return res


class MaterialIssue(models.Model):
    _name = 'combine.material.issue'
    _description = 'Material Issue Note'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'combine.stores.print.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(default=lambda self: _('New'), readonly=True, copy=False)
    date = fields.Date(default=fields.Date.context_today, required=True, tracking=True)
    department_id = fields.Many2one('combine.production.department', string='Issued To', required=True, tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    warehouse_id = fields.Many2one('stock.warehouse', required=True, check_company=True,
                                   default=lambda self: self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1))
    location_id = fields.Many2one('stock.location', string='Issue From', required=True,
                                  compute='_compute_location', store=True, readonly=False, precompute=True,
                                  domain="[('usage', '=', 'internal'), ('company_id', '=', company_id)]")
    requested_by = fields.Char(string='Requested By')
    issued_by_id = fields.Many2one('res.users', string='Issued By', default=lambda self: self.env.user)
    state = fields.Selection([('draft', 'Draft'), ('done', 'Issued'), ('cancel', 'Cancelled')],
                             default='draft', required=True, tracking=True, copy=False)
    line_ids = fields.One2many('combine.material.issue.line', 'issue_id', string='Items', copy=True)
    move_ids = fields.Many2many('stock.move', string='Stock Moves', readonly=True, copy=False)
    currency_id = fields.Many2one(related='company_id.currency_id')
    total_value = fields.Monetary(compute='_compute_total_value', store=True, string='Total Value')
    note = fields.Text()

    @api.depends('warehouse_id')
    def _compute_location(self):
        for issue in self:
            issue.location_id = issue.location_id or issue.warehouse_id.lot_stock_id

    @api.depends('line_ids.value')
    def _compute_total_value(self):
        for issue in self:
            issue.total_value = sum(issue.line_ids.mapped('value'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('combine.material.issue') or _('New')
        return super().create(vals_list)

    def action_issue(self):
        for issue in self:
            if issue.state != 'draft':
                continue
            if not issue.line_ids.filtered(lambda l: l.qty > 0):
                raise UserError(_('Add the items to issue.'))
            dest = issue.department_id.location_id
            if not dest:
                raise UserError(_('Department %s has no consumption location.', issue.department_id.name))
            short = []
            for line in issue.line_ids.filtered(lambda l: l.qty > 0):
                available = line.product_id.with_context(location=issue.location_id.id).qty_available
                need = line.uom_id._compute_quantity(line.qty, line.product_id.uom_id)
                if float_compare(need, available, precision_rounding=line.product_id.uom_id.rounding) > 0:
                    short.append(_('%(item)s: need %(need)s, available %(avail)s',
                                   item=line.product_id.display_name, need=need, avail=available))
            if short:
                raise UserError(_('Not enough stock in %(loc)s:\n%(lines)s', loc=issue.location_id.display_name, lines='\n'.join(short)))
            moves = self.env['stock.move']
            for line in issue.line_ids.filtered(lambda l: l.qty > 0):
                move = self.env['stock.move'].create({
                    'product_id': line.product_id.id, 'product_uom_qty': line.qty, 'product_uom': line.uom_id.id,
                    'location_id': issue.location_id.id, 'location_dest_id': dest.id,
                    'origin': issue.name, 'company_id': issue.company_id.id,
                })
                move._action_confirm()
                move._action_assign()
                move.quantity = line.qty
                move.picked = True
                move._action_done()
                # the value the stock left the warehouse at (average / FIFO cost)
                value = abs(move.value) if 'value' in move._fields else line.qty * line.product_id.standard_price
                line.write({'move_id': move.id, 'value': value, 'unit_cost': value / line.qty if line.qty else 0.0})
                moves |= move
            issue.write({'state': 'done', 'move_ids': [Command.set(moves.ids)]})
        return True

    def action_cancel(self):
        if any(issue.state == 'done' for issue in self):
            raise UserError(_('An issued note cannot be cancelled; return the material with a new note instead.'))
        self.write({'state': 'cancel'})

    def action_draft(self):
        self.filtered(lambda i: i.state == 'cancel').write({'state': 'draft'})

    # print
    def _print_title(self):
        return 'Material Issue Note'

    def _print_info(self):
        return [('Issue No.', self.name), ('Date', self._print_date(self.date)), ('Issued To', self.department_id.name),
                ('Issue From', self.location_id.display_name), ('Requested By', self.requested_by or '-'),
                ('Issued By', self.issued_by_id.name or '-')]

    def _print_columns(self):
        return [('Sr.', 'c'), ('Item', ''), ('Quantity', 'n'), ('UoM', 'c'), ('Cost / Unit', 'n'), ('Value', 'n'), ('Remarks', '')]

    def _print_rows(self):
        return [[i, l.product_id.display_name, num(l.qty), l.uom_id.name, num(l.unit_cost, 4) if self.state == 'done' else '-',
                 num(l.value) if self.state == 'done' else '-', l.note or ''] for i, l in enumerate(self.line_ids, 1)]

    def _print_totals(self):
        return {2: num(sum(self.line_ids.mapped('qty'))), 5: num(self.total_value) if self.state == 'done' else '-'}

    def _print_signatures(self):
        return ['Requested by', 'Issued by (Store)', 'Received by (Department)']


class MaterialIssueLine(models.Model):
    _name = 'combine.material.issue.line'
    _description = 'Material Issue Line'

    issue_id = fields.Many2one('combine.material.issue', required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one('product.product', string='Item', required=True, domain=[('is_storable', '=', True)])
    qty = fields.Float(string='Quantity', digits='Product Unit')
    uom_id = fields.Many2one('uom.uom', string='UoM', compute='_compute_uom', store=True, readonly=False, precompute=True, required=True)
    available_qty = fields.Float(string='Available', compute='_compute_available', digits='Product Unit')
    currency_id = fields.Many2one(related='issue_id.currency_id')
    unit_cost = fields.Float(string='Cost / Unit', digits=(16, 4), readonly=True)
    value = fields.Monetary(string='Value', readonly=True)
    move_id = fields.Many2one('stock.move', readonly=True)
    note = fields.Char(string='Remarks')

    @api.depends('product_id')
    def _compute_uom(self):
        for line in self:
            line.uom_id = line.uom_id or line.product_id.uom_id

    @api.depends('product_id', 'issue_id.location_id')
    def _compute_available(self):
        for line in self:
            line.available_qty = line.product_id.with_context(location=line.issue_id.location_id.id).qty_available \
                if line.product_id and line.issue_id.location_id else 0.0
