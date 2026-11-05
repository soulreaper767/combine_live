from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare

# the mill's process flows (department name, code, type)
STANDARD_DEPARTMENTS = [
    ('Blow Room', 'BR', 'process'), ('Carding', 'CD', 'process'), ('Breaker Drawing', 'BD', 'process'),
    ('Sliver Lap Preparation', 'SLP', 'process'), ('Comber Preparation', 'CP', 'process'), ('Combing', 'CM', 'process'),
    ('Finisher Drawing', 'FD', 'process'), ('Speed Frame / Simplex', 'SF', 'process'), ('Ring Spinning', 'RS', 'process'),
    ('Open-End / Rotor Spinning', 'OE', 'process'), ('Winding', 'WD', 'process'),
    ('Yarn Testing & Quality Control', 'QC', 'qc'), ('Packing', 'PK', 'packing'),
]
STANDARD_ROUTES = [
    ('Carded Yarn', 'CARDED', 'carded', ['BR', 'CD', 'BD', 'FD', 'SF', 'RS', 'WD', 'QC', 'PK']),
    ('Combed Yarn', 'COMBED', 'combed', ['BR', 'CD', 'BD', 'SLP', 'CP', 'CM', 'FD', 'SF', 'RS', 'WD', 'QC', 'PK']),
    ('Open-End / Rotor Yarn', 'OE', 'open_end', ['BR', 'CD', 'BD', 'FD', 'OE', 'WD', 'QC', 'PK']),
]
QC_STAGES = [('raw_cotton', 'Raw Cotton Testing'), ('sliver', 'Sliver Testing'), ('roving', 'Roving Testing'),
             ('yarn', 'Yarn Testing'), ('final', 'Final Quality Approval')]
QC_PARAMETERS = {
    'raw_cotton': [('Staple Length', 'mm'), ('Micronaire', 'µg/inch'), ('Strength', 'g/tex'), ('Uniformity Index', '%'),
                   ('Trash Content', '%'), ('Moisture', '%')],
    'sliver': [('Hank', 'Ne'), ('U%', '%'), ('Neps', '/g'), ('Sliver Weight', 'g/yd')],
    'roving': [('Hank', 'Ne'), ('U%', '%'), ('TPI', 'twist/inch')],
    'yarn': [('Count', 'Ne'), ('Count CV', '%'), ('CSP', ''), ('U%', '%'), ('Thin Places', '/km'), ('Thick Places', '/km'),
             ('Neps', '/km'), ('Hairiness', 'H'), ('TPI', 'twist/inch')],
    'final': [('Count', 'Ne'), ('CSP', ''), ('Appearance', 'grade'), ('Moisture', '%'), ('Cone Weight', 'kg'), ('Packing Check', 'ok')],
}
WASTE_CLASSES = [('reusable', 'Reusable (back to Blow Room)'), ('recyclable', 'Recyclable / Reprocess'),
                 ('saleable', 'Saleable'), ('hard', 'Hard Waste / Disposal')]


class ProductionDepartment(models.Model):
    _inherit = 'combine.production.department'

    dept_type = fields.Selection([('process', 'Production Process'), ('qc', 'Quality Control'), ('packing', 'Packing'),
                                  ('other', 'Other')], string='Type', default='process', required=True)
    waste_product_id = fields.Many2one('product.product', string='Waste Item',
                                       help='Waste of this department (Blow Room waste, flat strips, comber noil, pneumafil, '
                                            'hard waste...). Batches record their waste as this item.')


# ============================================================ process routes
class ProcessRoute(models.Model):
    """A product flow through the mill: Carded, Combed, Open-End... Each
    step is a department; a batch's output goes to the next step."""
    _name = 'combine.process.route'
    _description = 'Process Route'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    code = fields.Char()
    sequence = fields.Integer(default=10)
    yarn_type = fields.Selection([('carded', 'Carded'), ('combed', 'Combed'), ('open_end', 'Open-End / Rotor'),
                                  ('other', 'Other')], default='other')
    step_ids = fields.One2many('combine.process.route.step', 'route_id', string='Process Steps', copy=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    flow_text = fields.Char(string='Flow', compute='_compute_flow_text')

    @api.depends('step_ids.department_id', 'step_ids.sequence')
    def _compute_flow_text(self):
        for route in self:
            route.flow_text = '  >  '.join(route.step_ids.sorted('sequence').department_id.mapped('name'))

    def _steps(self):
        return self.step_ids.sorted(lambda s: (s.sequence, s.id))

    def _next_department(self, department, skip_qc=True):
        """The department after `department` on this route (QC steps are a check, not a transfer)."""
        self.ensure_one()
        steps = self._steps()
        depts = steps.department_id
        if department not in depts:
            return self.env['combine.production.department']
        after = steps[list(depts).index(department) + 1:]
        for step in after:
            if skip_qc and step.department_id.dept_type == 'qc':
                continue
            return step.department_id
        return self.env['combine.production.department']

    def _requires_qc_before(self, department):
        """True when a QC step stands right before `department` on this route."""
        self.ensure_one()
        steps = list(self._steps())
        for i, step in enumerate(steps):
            if step.department_id == department:
                return i > 0 and steps[i - 1].department_id.dept_type == 'qc'
        return False

    @api.model
    def action_load_standard_flows(self):
        """Create the mill's departments and the Carded / Combed / Open-End
        routes - only what does not exist yet; nothing existing is changed."""
        Dept = self.env['combine.production.department'].with_context(active_test=False)
        by_code = {}
        created_d = created_r = 0
        for seq, (name, code, dtype) in enumerate(STANDARD_DEPARTMENTS, 1):
            dept = Dept.search(['|', ('code', '=', code), ('name', '=ilike', name), ('company_id', '=', self.env.company.id)], limit=1)
            if not dept:
                dept = Dept.create({'name': name, 'code': code, 'dept_type': dtype, 'sequence': seq * 10})
                created_d += 1
            by_code[code] = dept
        for seq, (name, code, ytype, codes) in enumerate(STANDARD_ROUTES, 1):
            if self.with_context(active_test=False).search_count([('code', '=', code), ('company_id', '=', self.env.company.id)]):
                continue
            self.create({'name': name, 'code': code, 'yarn_type': ytype, 'sequence': seq * 10,
                         'step_ids': [Command.create({'sequence': (i + 1) * 10, 'department_id': by_code[c].id})
                                      for i, c in enumerate(codes)]})
            created_r += 1
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'type': 'success', 'title': _('Spinning flows loaded'),
                           'message': _('%(d)s departments and %(r)s routes created; existing ones left as they were.',
                                        d=created_d, r=created_r),
                           'next': {'type': 'ir.actions.client', 'tag': 'reload'}}}


class ProcessRouteStep(models.Model):
    _name = 'combine.process.route.step'
    _description = 'Process Route Step'
    _order = 'sequence, id'

    route_id = fields.Many2one('combine.process.route', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    department_id = fields.Many2one('combine.production.department', required=True)
    dept_type = fields.Selection(related='department_id.dept_type')
    output_note = fields.Char(string='Output', help='e.g. Lap, Card Sliver, Drawn Sliver, Roving, Yarn on Cops, Cones, Packed Yarn')


# ============================================================ quality control
class QualityTest(models.Model):
    """Raw cotton / sliver / roving / yarn testing and the final quality
    approval that authorises packing."""
    _name = 'combine.quality.test'
    _description = 'Quality Test'
    _inherit = ['mail.thread', 'combine.stores.print.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(default=lambda self: _('New'), readonly=True, copy=False)
    date = fields.Date(required=True, default=fields.Date.context_today)
    stage = fields.Selection(QC_STAGES, required=True, default='yarn', tracking=True)
    department_id = fields.Many2one('combine.production.department')
    batch_id = fields.Many2one('combine.production.batch', string='Batch')
    lot_no = fields.Char(string='Lot / Batch Ref.')
    product_id = fields.Many2one('product.product', string='Item')
    partner_id = fields.Many2one('res.partner', string='Supplier', help='Raw cotton: the supplier of the bales.')
    grn_id = fields.Many2one('combine.grn', string='GRN')
    line_ids = fields.One2many('combine.quality.test.line', 'test_id', copy=True)
    result = fields.Selection([('pass', 'Approved'), ('hold', 'On Hold'), ('fail', 'Rejected')], tracking=True)
    state = fields.Selection([('draft', 'Draft'), ('done', 'Done')], default='draft', required=True, tracking=True)
    tested_by_id = fields.Many2one('res.users', default=lambda self: self.env.user)
    approved_by_id = fields.Many2one('res.users', readonly=True, copy=False)
    note = fields.Text()
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('combine.quality.test') or _('New')
        tests = super().create(vals_list)
        for test in tests.filtered(lambda t: not t.line_ids):
            test._load_parameters()
        return tests

    @api.onchange('batch_id')
    def _onchange_batch(self):
        if self.batch_id:
            self.lot_no = self.batch_id.lot_no or self.batch_id.name
            self.product_id = self.batch_id.product_id
            self.department_id = self.batch_id.department_id

    @api.onchange('stage')
    def _onchange_stage(self):
        if self.state == 'draft':
            self.line_ids = [Command.clear()] + [Command.create({'parameter': p, 'unit': u}) for p, u in QC_PARAMETERS.get(self.stage, [])]

    def _load_parameters(self):
        self.write({'line_ids': [Command.create({'parameter': p, 'unit': u}) for p, u in QC_PARAMETERS.get(self.stage, [])]})

    def action_done(self):
        for test in self:
            if not test.result:
                raise UserError(_('%s: set the result (Approved / On Hold / Rejected).', test.name))
            test.write({'state': 'done', 'approved_by_id': self.env.user.id})

    def action_draft(self):
        self.write({'state': 'draft'})

    def _print_title(self):
        return dict(QC_STAGES)[self.stage] if self.stage != 'final' else 'Final Quality Approval / Packing Authorization'

    def _print_info(self):
        return [('Test No.', self.name), ('Date', self._print_date(self.date)), ('Stage', dict(QC_STAGES)[self.stage]),
                ('Item', self.product_id.display_name or '-'), ('Lot / Batch', self.lot_no or self.batch_id.name or '-'),
                ('Department', self.department_id.name or (self.partner_id.name and 'Supplier: %s' % self.partner_id.name) or '-'),
                ('Result', dict(self._fields['result'].selection).get(self.result, '-')), ('Approved By', self.approved_by_id.name or '-')]

    def _print_columns(self):
        return [('Sr.', 'c'), ('Parameter', ''), ('Unit', 'c'), ('Standard', 'c'), ('Result', 'c'), ('Within Standard', 'c'), ('Remarks', '')]

    def _print_rows(self):
        return [[i, l.parameter, l.unit or '', l.standard or '', l.value or '', 'Yes' if l.ok else 'No', l.note or '']
                for i, l in enumerate(self.line_ids, 1)]

    def _print_totals(self):
        return {}

    def _print_signatures(self):
        return ['Tested by', 'QC Manager', 'Production Manager']


class QualityTestLine(models.Model):
    _name = 'combine.quality.test.line'
    _description = 'Quality Test Parameter'

    test_id = fields.Many2one('combine.quality.test', required=True, ondelete='cascade', index=True)
    parameter = fields.Char(required=True)
    unit = fields.Char()
    standard = fields.Char(string='Standard / Range')
    value = fields.Char(string='Result')
    ok = fields.Boolean(string='Within Standard', default=True)
    note = fields.Char(string='Remarks')


# ============================================================ waste
class WasteCollection(models.Model):
    """Waste collected from the departments, segregated, weighed and
    classified, received into the waste store at its standard value -
    from there it is reissued (recycling), reprocessed or sold."""
    _name = 'combine.waste.collection'
    _description = 'Waste Collection Note'
    _inherit = ['mail.thread', 'combine.stores.print.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(default=lambda self: _('New'), readonly=True, copy=False)
    date = fields.Date(required=True, default=fields.Date.context_today)
    location_id = fields.Many2one('stock.location', string='Waste Store', required=True, domain="[('usage', '=', 'internal')]",
                                  default=lambda self: self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1).lot_stock_id)
    line_ids = fields.One2many('combine.waste.collection.line', 'collection_id', copy=True)
    state = fields.Selection([('draft', 'Draft'), ('done', 'Received')], default='draft', required=True, tracking=True)
    move_ids = fields.Many2many('stock.move', string='Stock Moves', readonly=True, copy=False)
    total_value = fields.Float(compute='_compute_total', digits=(16, 2))
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    note = fields.Text()

    @api.depends('line_ids.value')
    def _compute_total(self):
        for c in self:
            c.total_value = sum(c.line_ids.mapped('value'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('combine.waste.collection') or _('New')
        return super().create(vals_list)

    def action_receive(self):
        Ledger = self.env['combine.dept.ledger'].sudo()
        Card = self.env['combine.cost.card']
        for c in self.filtered(lambda c: c.state == 'draft'):
            lines = c.line_ids.filtered(lambda l: l.net_weight > 0)
            if not lines:
                raise UserError(_('Enter the waste weighed.'))
            short = []
            for l in lines:
                have = Ledger._balance(l.department_id, l.product_id, c.date)[0]
                if float_compare(l.net_weight, have, precision_digits=3) > 0:
                    short.append(_('%(dept)s - %(item)s: collected %(q)s kg, department book shows %(h)s kg',
                                   dept=l.department_id.name, item=l.product_id.display_name, q=l.net_weight, h=round(have, 3)))
            if short:
                raise UserError(_('More waste than the departments recorded:\n%s\nRecord it on the batches first, or post a WIP count.', '\n'.join(short)))
            moves = self.env['stock.move']
            for l in lines:
                l.value = l.net_weight * Card._std_cost(l.product_id, c.date)
                Ledger.create({'date': c.date, 'department_id': l.department_id.id, 'product_id': l.product_id.id,
                               'qty': -l.net_weight, 'value': 0.0, 'kind': 'waste_out', 'company_id': c.company_id.id})
                move = self.env['stock.move'].create({
                    'product_id': l.product_id.id, 'product_uom_qty': l.net_weight, 'product_uom': l.product_id.uom_id.id,
                    'location_id': l.department_id.location_id.id, 'location_dest_id': c.location_id.id,
                    'origin': c.name, 'company_id': c.company_id.id, 'x_waste_line_id': l.id})
                move._action_confirm()
                move.quantity = l.net_weight
                move.picked = True
                move._action_done()
                moves |= move
            c.write({'state': 'done', 'move_ids': [Command.set(moves.ids)]})

    def _print_title(self):
        return 'Waste Collection Note'

    def _print_info(self):
        return [('Note No.', self.name), ('Date', self._print_date(self.date)), ('Received Into', self.location_id.display_name)]

    def _print_columns(self):
        return [('Sr.', 'c'), ('Department', ''), ('Waste Item', ''), ('Classification', 'c'), ('Bags', 'n'),
                ('Gross Wt.', 'n'), ('Tare Wt.', 'n'), ('Net Wt.', 'n'), ('Value', 'n')]

    def _print_rows(self):
        cls = dict(WASTE_CLASSES)
        return [[i, l.department_id.name, l.product_id.display_name, cls.get(l.classification, ''), f'{l.bags:,.0f}',
                 f'{l.gross_weight:,.2f}', f'{l.tare_weight:,.2f}', f'{l.net_weight:,.2f}', f'{l.value:,.2f}']
                for i, l in enumerate(self.line_ids, 1)]

    def _print_totals(self):
        return {4: f"{sum(self.line_ids.mapped('bags')):,.0f}", 7: f"{sum(self.line_ids.mapped('net_weight')):,.2f}",
                8: f'{self.total_value:,.2f}'}

    def _print_signatures(self):
        return ['Collected by', 'Weighed by', 'Waste Store Incharge']


class WasteCollectionLine(models.Model):
    _name = 'combine.waste.collection.line'
    _description = 'Waste Collection Line'

    collection_id = fields.Many2one('combine.waste.collection', required=True, ondelete='cascade', index=True)
    department_id = fields.Many2one('combine.production.department', required=True)
    product_id = fields.Many2one('product.product', string='Waste Item', required=True,
                                 compute='_compute_product', store=True, readonly=False, precompute=True)
    classification = fields.Selection(WASTE_CLASSES, default='saleable', required=True)
    bags = fields.Float(digits=(16, 0))
    gross_weight = fields.Float(string='Gross Wt. (kg)', digits=(16, 3))
    tare_weight = fields.Float(string='Tare Wt. (kg)', digits=(16, 3))
    net_weight = fields.Float(string='Net Wt. (kg)', compute='_compute_net', store=True, readonly=False, digits=(16, 3))
    value = fields.Float(digits=(16, 2), readonly=True)

    @api.depends('department_id')
    def _compute_product(self):
        for line in self:
            line.product_id = line.product_id or line.department_id.waste_product_id

    @api.depends('gross_weight', 'tare_weight')
    def _compute_net(self):
        for line in self:
            if line.gross_weight:
                line.net_weight = line.gross_weight - line.tare_weight


# ============================================================ production budget
class ProductionBudget(models.Model):
    """Monthly production budget: planned output, waste % and cost per unit
    per department and item - the yardstick for actual vs budget."""
    _name = 'combine.production.budget'
    _description = 'Production Budget'
    _inherit = ['mail.thread']
    _order = 'date_from desc'

    name = fields.Char(required=True, default=lambda self: _('Budget %s', fields.Date.context_today(self).strftime('%b-%y')))
    date_from = fields.Date(required=True, default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date(required=True)
    line_ids = fields.One2many('combine.production.budget.line', 'budget_id', copy=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)

    @api.onchange('date_from')
    def _onchange_date_from(self):
        if self.date_from:
            self.date_to = fields.Date.end_of(self.date_from, 'month')


class ProductionBudgetLine(models.Model):
    _name = 'combine.production.budget.line'
    _description = 'Production Budget Line'

    budget_id = fields.Many2one('combine.production.budget', required=True, ondelete='cascade', index=True)
    department_id = fields.Many2one('combine.production.department', required=True)
    product_id = fields.Many2one('product.product', string='Output Item', required=True)
    budget_qty = fields.Float(string='Budgeted Output', digits='Product Unit')
    budget_waste_pct = fields.Float(string='Budgeted Waste %', digits=(5, 2))
    budget_cost = fields.Float(string='Budgeted Cost / Unit', digits=(16, 4),
                               compute='_compute_budget_cost', store=True, readonly=False,
                               help='Defaults to the standard cost card on the budget start date.')

    @api.depends('product_id', 'budget_id.date_from')
    def _compute_budget_cost(self):
        Card = self.env['combine.cost.card']
        for line in self:
            if line.product_id and not line.budget_cost:
                line.budget_cost = Card._std_cost(line.product_id, line.budget_id.date_from)


# ============================================================ batch additions
class ProductionBatch(models.Model):
    _inherit = 'combine.production.batch'

    route_id = fields.Many2one('combine.process.route', string='Process Route', tracking=True)
    machine_no = fields.Char(string='Machine No.')
    qc_test_id = fields.Many2one('combine.quality.test', string='Final QC Approval',
                                 domain="[('stage', '=', 'final'), ('result', '=', 'pass'), ('state', '=', 'done')]",
                                 help='Packing authorization: the approved final quality test of this lot.')
    qc_required = fields.Boolean(compute='_compute_qc_required')
    input_qty = fields.Float(string='Input Qty', compute='_compute_input_qty', store=True, digits='Product Unit')
    waste_pct = fields.Float(string='Waste %', compute='_compute_input_qty', store=True, digits=(5, 2))

    @api.depends('input_ids.qty')
    def _compute_input_qty(self):
        for b in self:
            b.input_qty = sum(b.input_ids.mapped('qty'))
            b.waste_pct = b.qty_waste / b.input_qty * 100 if b.input_qty else 0.0

    @api.depends('route_id', 'department_id')
    def _compute_qc_required(self):
        for b in self:
            b.qc_required = bool(b.route_id and b.department_id and b.route_id._requires_qc_before(b.department_id))

    @api.depends('department_id', 'route_id')
    def _compute_next(self):
        for batch in self:
            nxt = batch.route_id._next_department(batch.department_id) if batch.route_id and batch.department_id else False
            batch.next_department_id = nxt or batch.next_department_id or batch.department_id.next_department_id

    @api.onchange('department_id', 'route_id')
    def _onchange_department_flow(self):
        if self.department_id.waste_product_id and not self.waste_product_id:
            self.waste_product_id = self.department_id.waste_product_id
        if self.department_id.dept_type == 'packing' or (self.route_id and self.department_id
                                                          and not self.route_id._next_department(self.department_id)):
            self.destination = 'store'

    def action_complete(self):
        for b in self.filtered(lambda b: b.state == 'draft'):
            if b.qc_required and not b.qc_test_id:
                raise UserError(_('%(b)s: %(d)s needs the approved final quality test of the lot (packing authorization).',
                                  b=b.name, d=b.department_id.name))
            if not b.waste_product_id and b.department_id.waste_product_id:
                b.waste_product_id = b.department_id.waste_product_id
        return super().action_complete()

    def _print_info(self):
        info = super()._print_info()
        if self.route_id:
            info.append(('Route', self.route_id.name))
        if self.machine_no:
            info.append(('Machine', self.machine_no))
        if self.qc_test_id:
            info.append(('QC Approval', self.qc_test_id.name))
        return info


class DepartmentLedger(models.Model):
    _inherit = 'combine.dept.ledger'

    kind = fields.Selection(selection_add=[('waste_out', 'Waste Collected')], ondelete={'waste_out': 'cascade'})


class StockMove(models.Model):
    _inherit = 'stock.move'

    x_waste_line_id = fields.Many2one('combine.waste.collection.line', readonly=True, index='btree_not_null')

    def _get_value_from_production(self, quantity, at_date=None):
        if self.x_waste_line_id and self.x_waste_line_id.net_weight:
            line = self.x_waste_line_id
            return {'value': line.value * quantity / line.net_weight, 'quantity': quantity,
                    'description': _('Waste at standard value, %s', line.collection_id.name)}
        return super()._get_value_from_production(quantity, at_date)
