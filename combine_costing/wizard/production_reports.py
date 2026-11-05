from collections import defaultdict

from odoo import _, fields, models

REPORTS = [
    ('daily', 'Daily Production Report (FG + departments)'),
    ('department', 'Department Production Report (batch by batch)'),
    ('fg', 'Finished Goods Production Report'),
    ('wip', 'WIP Summary'),
    ('process', 'Process Cost Build-up (incremental cost per process)'),
    ('budget', 'Actual vs Budget'),
]


class ProductionReportWizard(models.TransientModel):
    """All production reports in one place, every one in the house style
    (PDF + Excel): daily production with finished goods first, each
    department's batches, FG production by item and day, WIP lying in the
    departments, cost added process by process, actual against budget."""
    _name = 'combine.production.report.wizard'
    _inherit = 'combine.register.mixin'
    _description = 'Production Reports'
    _register_report_xmlid = 'combine_costing.action_report_production'

    report = fields.Selection(REPORTS, required=True, default='daily')
    date_from = fields.Date(default=fields.Date.context_today)
    department_ids = fields.Many2many('combine.production.department', 'combine_prodrep_dept_rel', 'wizard_id', 'dept_id',
                                      string='Departments', help='Leave empty for all.')
    route_id = fields.Many2one('combine.process.route', string='Process Route',
                               help='Process cost build-up: the route whose steps are followed (empty = department order).')
    budget_id = fields.Many2one('combine.production.budget', string='Budget')

    # ------------------------------------------------------------------ helpers
    def _batches(self):
        dom = [('company_id', '=', self.env.company.id), ('state', '=', 'done'),
               ('date', '>=', self.date_from), ('date', '<=', self.date_to)]
        if self.department_ids:
            dom.append(('department_id', 'in', self.department_ids.ids))
        return self.env['combine.production.batch'].search(dom, order='date, department_id, id').filtered(
            lambda b: self._register_product_ok(b.product_id))

    @staticmethod
    def _std_waste(batch):
        return batch.card_id.std_waste_pct if batch.card_id else 0.0

    COLS = None

    def _prod_columns(self):
        return [(_('Item / Department'), 't'), (_('Batches'), 'c'), (_('Input Qty'), 'q'), (_('Output Qty'), 'q'),
                (_('Waste Qty'), 'q'), (_('Waste %'), 'c'), (_('Std. Waste %'), 'c'), (_('Actual Cost'), 'n'),
                (_('Standard Cost'), 'n'), (_('Variance'), 'n'), (_('Actual / Unit'), 'n')]

    def _prod_row(self, label, batches):
        inp = sum(batches.mapped('input_qty'))
        out = sum(batches.mapped('qty_produced'))
        waste = sum(batches.mapped('qty_waste'))
        std_w = [self._std_waste(b) for b in batches if self._std_waste(b)]
        actual, std = sum(batches.mapped('actual_cost')), sum(batches.mapped('std_cost'))
        return [label, len(batches), inp, out, waste, f'{waste / inp * 100:,.2f}%' if inp else '-',
                f'{sum(std_w) / len(std_w):,.2f}%' if std_w else '-', actual, std, actual - std, actual / out if out else 0.0]

    @staticmethod
    def _sum(rows, cols):
        return {i: sum(r[i] for r in rows if isinstance(r[i], (int, float))) for i in cols}

    def _fg_batches(self, batches):
        return batches.filtered(lambda b: b.destination == 'store')

    # ------------------------------------------------------------------ data
    def _register_data(self):
        self.ensure_one()
        return getattr(self, '_data_' + self.report)()

    def _wrap(self, columns, groups, totals=None, extra_filters=()):
        filters = self._register_filter_lines()
        if self.department_ids:
            filters.append((_('Departments'), ', '.join(self.department_ids.mapped('name'))))
        filters += list(extra_filters)
        return {'title': dict(REPORTS)[self.report].split(' (')[0], 'filters': filters, 'columns': columns,
                'groups': groups, 'totals': totals or {}}

    def _data_daily(self):
        batches = self._batches()
        cols = self._prod_columns()
        groups = []
        fg = self._fg_batches(batches)
        if fg:
            rows = [self._prod_row(p.display_name, fg.filtered(lambda b, p=p: b.product_id == p)) for p in fg.product_id]
            groups.append({'title': _('A. Finished Goods Produced'), 'sub': _('received into the store'),
                           'rows': rows, 'totals': self._sum(rows, (1, 3, 7, 8, 9)) if len({b.uom_id for b in fg}) == 1
                           else self._sum(rows, (1, 7, 8, 9))})
        depts = batches.department_id.sorted(lambda d: (d.sequence, d.name))
        rows = [self._prod_row(d.name + '  -  ' + ', '.join(batches.filtered(lambda b, d=d: b.department_id == d).product_id.mapped('display_name')),
                               batches.filtered(lambda b, d=d: b.department_id == d)) for d in depts]
        if rows:
            groups.append({'title': _('B. Department-wise Production'), 'sub': '', 'rows': rows, 'totals': self._sum(rows, (1, 7, 8, 9))})
        waste = defaultdict(float)
        for b in batches.filtered('qty_waste'):
            waste[(b.department_id, b.waste_product_id)] += b.qty_waste
        wrows = [[('%s  -  %s' % (d.name, w.display_name)) if w else d.name, '', None, None, q, '', '', None, None, None, None]
                 for (d, w), q in sorted(waste.items(), key=lambda kv: (kv[0][0].sequence, kv[0][0].name))]
        if wrows:
            groups.append({'title': _('C. Waste'), 'sub': '', 'rows': wrows, 'totals': self._sum(wrows, (4,))})
        return self._wrap(cols, groups)

    def _data_department(self):
        batches = self._batches()
        cols = [(_('Date'), 'd'), (_('Batch'), 't'), (_('Lot'), 'c'), (_('Shift'), 'c'), (_('Machine'), 'c'), (_('Output Item'), 't'),
                (_('Input Qty'), 'q'), (_('Output Qty'), 'q'), (_('Waste Qty'), 'q'), (_('Waste %'), 'c'), (_('Sent To'), 't'),
                (_('Actual Cost'), 'n')]
        groups = []
        for d in batches.department_id.sorted(lambda d: (d.sequence, d.name)):
            bs = batches.filtered(lambda b, d=d: b.department_id == d)
            rows = [[b.date, b.name, b.lot_no or '', b.shift or '', b.machine_no or '', b.product_id.display_name, b.input_qty,
                     b.qty_produced, b.qty_waste, f'{b.waste_pct:,.2f}%',
                     {'next': b.next_department_id.name, 'store': _('Store'), 'stay': _('Stays')}.get(b.destination) or '',
                     b.actual_cost] for b in bs]
            totals = self._sum(rows, (11,))
            if len(bs.uom_id) == 1:
                totals.update(self._sum(rows, (6, 7, 8)))
            groups.append({'title': d.name, 'sub': _('Batches: %s', len(rows)), 'rows': rows, 'totals': totals})
        return self._wrap(cols, groups)

    def _data_fg(self):
        fg = self._fg_batches(self._batches())
        cols = [(_('Date'), 'd'), (_('Batches'), 'c'), (_('Quantity'), 'q'), (_('UoM'), 'c'), (_('Actual Cost'), 'n'),
                (_('Standard Cost'), 'n'), (_('Variance'), 'n'), (_('Actual / Unit'), 'n'), (_('Std. / Unit'), 'n')]
        groups = []
        for p in fg.product_id.sorted('display_name'):
            bs = fg.filtered(lambda b, p=p: b.product_id == p)
            rows = []
            for day in sorted(set(bs.mapped('date'))):
                d = bs.filtered(lambda b, day=day: b.date == day)
                q, a, s = sum(d.mapped('qty_produced')), sum(d.mapped('actual_cost')), sum(d.mapped('std_cost'))
                rows.append([day, len(d), q, p.uom_id.name, a, s, a - s, a / q if q else 0.0, s / q if q else 0.0])
            groups.append({'title': p.display_name, 'sub': '', 'rows': rows, 'totals': self._sum(rows, (1, 2, 4, 5, 6))})
        grand = {i: sum(g['totals'][i] for g in groups) for i in (1, 4, 5, 6)} if groups else {}
        if groups and len(fg.uom_id) == 1:
            grand[2] = sum(g['totals'][2] for g in groups)
        return self._wrap(cols, groups, grand)

    def _data_wip(self):
        Ledger = self.env['combine.dept.ledger']
        dom = [('company_id', '=', self.env.company.id), ('date', '<=', self.date_to)]
        if self.department_ids:
            dom.append(('department_id', 'in', self.department_ids.ids))
        data = Ledger._read_group(dom, ['department_id', 'product_id'], ['qty:sum', 'value:sum'])
        cols = [(_('Item'), 't'), (_('Quantity'), 'q'), (_('UoM'), 'c'), (_('Value'), 'n'), (_('Value / Unit'), 'n')]
        by_dept = defaultdict(list)
        for dept, product, qty, value in data:
            if abs(qty) < 0.0001 or not self._register_product_ok(product):
                continue
            by_dept[dept].append([product.display_name, qty, product.uom_id.name, value, value / qty if qty else 0.0])
        groups = [{'title': d.name, 'sub': '', 'rows': sorted(rows), 'totals': self._sum(rows, (3,))}
                  for d, rows in sorted(by_dept.items(), key=lambda kv: (kv[0].sequence, kv[0].name))]
        grand = {3: sum(g['totals'][3] for g in groups)} if groups else {}
        return self._wrap(cols, groups, grand, [(_('As on'), self.date_to.strftime('%d-%b-%y'))])

    def _data_process(self):
        batches = self._batches()
        Card = self.env['combine.cost.card']
        if self.route_id:
            depts = self.route_id._steps().department_id.filtered(lambda d: d.dept_type != 'qc')
        else:
            depts = batches.department_id.sorted(lambda d: (d.sequence, d.name))
        cols = [(_('Process'), 't'), (_('Output Item'), 't'), (_('Output Qty'), 'q'), (_('Cost Brought In'), 'n'),
                (_('Cost Added'), 'n'), (_('Total Cost'), 'n'), (_('Cost / Unit'), 'n'), (_('Added / Unit'), 'n'),
                (_('Std. Cost / Unit'), 'n'), (_('Std. Added / Unit'), 'n'), (_('Variance / Unit'), 'n')]
        rows = []
        for d in depts:
            bs = batches.filtered(lambda b, d=d: b.department_id == d)
            for p in bs.product_id:
                pb = bs.filtered(lambda b, p=p: b.product_id == p)
                q = sum(pb.mapped('qty_produced'))
                mat, conv = sum(pb.mapped('material_cost')), sum(pb.mapped('conversion_actual'))
                card = Card._card_for(p, self.date_to)
                std_unit = Card._std_cost(p, self.date_to)
                unit = (mat + conv) / q if q else 0.0
                rows.append([d.name, p.display_name, q, mat, conv, mat + conv, unit, conv / q if q else 0.0,
                             std_unit, card.conversion_cost if card else 0.0, unit - std_unit])
        groups = [{'title': self.route_id.name or _('All processes'), 'sub': self.route_id.flow_text or '', 'rows': rows,
                   'totals': self._sum(rows, (4,))}] if rows else []
        return self._wrap(cols, groups, extra_filters=[(_('Route'), self.route_id.name or _('department order'))])

    def _data_budget(self):
        budget = self.budget_id or self.env['combine.production.budget'].search([
            ('company_id', '=', self.env.company.id), ('date_from', '<=', self.date_to), ('date_to', '>=', self.date_from)], limit=1)
        batches = self._batches()
        cols = [(_('Item'), 't'), (_('Budget Qty'), 'q'), (_('Actual Qty'), 'q'), (_('Qty Variance'), 'q'), (_('Achieved %'), 'c'),
                (_('Budget Cost / Unit'), 'n'), (_('Actual Cost / Unit'), 'n'), (_('Cost Var. / Unit'), 'n'),
                (_('Cost Variance'), 'n'), (_('Budget Waste %'), 'c'), (_('Actual Waste %'), 'c')]
        keys = {}
        for l in budget.line_ids:
            if (not self.department_ids or l.department_id in self.department_ids) and self._register_product_ok(l.product_id):
                keys[(l.department_id, l.product_id)] = l
        for b in batches:
            keys.setdefault((b.department_id, b.product_id), None)
        by_dept = defaultdict(list)
        for (d, p), line in sorted(keys.items(), key=lambda kv: (kv[0][0].sequence, kv[0][0].name, kv[0][1].display_name)):
            bs = batches.filtered(lambda b, d=d, p=p: b.department_id == d and b.product_id == p)
            aq = sum(bs.mapped('qty_produced'))
            ac = sum(bs.mapped('actual_cost'))
            bq = line.budget_qty if line else 0.0
            bc = line.budget_cost if line else 0.0
            au = ac / aq if aq else 0.0
            inp = sum(bs.mapped('input_qty'))
            budgeted = bool(line)
            by_dept[d].append([p.display_name if budgeted else p.display_name + _(' (not budgeted)'),
                               bq if budgeted else None, aq, aq - bq if budgeted else None,
                               f'{aq / bq * 100:,.1f}%' if bq else '-', bc if budgeted else None, au,
                               au - bc if budgeted and aq else None, (au - bc) * aq if budgeted and aq else None,
                               f'{line.budget_waste_pct:,.2f}%' if line else '-',
                               f'{sum(bs.mapped("qty_waste")) / inp * 100:,.2f}%' if inp else '-'])
        groups = [{'title': d.name, 'sub': '', 'rows': rows, 'totals': self._sum(rows, (8,))} for d, rows in by_dept.items()]
        grand = {8: sum(g['totals'][8] for g in groups)} if groups else {}
        return self._wrap(cols, groups, grand, [(_('Budget'), budget.name or _('none for this period'))])
