from collections import defaultdict

from odoo import _, fields, models


def _dt_range(date_from, date_to):
    start = fields.Datetime.to_datetime(date_from)
    return start, fields.Datetime.add(fields.Datetime.to_datetime(date_to), days=1)


class StockMovementWizard(models.TransientModel):
    """Stock Movement: per item (lot / category) for the period - opening,
    received from suppliers, received from production, other in, issued to
    production, delivered, other out, closing; internal transfers shown
    alongside (they move stock between our own locations, not in or out)."""
    _name = 'combine.stock.movement.wizard'
    _inherit = 'combine.register.mixin'
    _description = 'Stock Movement Report'
    _register_report_xmlid = 'combine_costing.action_report_stock_movement'

    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse', help='Leave empty for all warehouses.')
    measure = fields.Selection([('qty', 'Quantity'), ('value', 'Value')], required=True, default='qty')
    group_by = fields.Selection([('item', 'Item-wise'), ('category', 'Category-wise'), ('lot', 'Lot / batch-wise')],
                                required=True, default='item')
    hide_zero = fields.Boolean(string='Hide items without stock or movement', default=True)

    COLS = ('opening', 'received', 'from_prod', 'other_in', 'issued', 'delivered', 'other_out', 'closing', 'internal')

    def _ours(self):
        dom = [('usage', '=', 'internal'), ('company_id', '=', self.env.company.id)]
        if self.warehouse_id:
            dom.append(('id', 'child_of', self.warehouse_id.view_location_id.id))
        return set(self.env['stock.location'].search(dom).ids)

    def _classify(self, ml, ours):
        src_in, dst_in = ml.location_id.id in ours, ml.location_dest_id.id in ours
        if src_in and dst_in:
            return 'internal' if ml.location_id != ml.location_dest_id else None
        if not src_in and dst_in:
            usage = ml.location_id.usage
            return {'supplier': 'received', 'production': 'from_prod'}.get(usage, 'other_in')
        if src_in and not dst_in:
            usage = ml.location_dest_id.usage
            return {'customer': 'delivered', 'production': 'issued'}.get(usage, 'other_out')
        return None

    def _register_data(self):
        self.ensure_one()
        ours = self._ours()
        start, end = _dt_range(self.date_from, self.date_to)
        MLs = self.env['stock.move.line'].search([
            ('state', '=', 'done'), ('company_id', '=', self.env.company.id), ('date', '<', end),
            '|', ('location_id', 'in', list(ours)), ('location_dest_id', 'in', list(ours))], order='date, id')
        data = defaultdict(lambda: defaultdict(float))
        keys = {}
        for ml in MLs:
            product = ml.product_id
            if not self._register_product_ok(product):
                continue
            kind = self._classify(ml, ours)
            if not kind:
                continue
            qty = ml.quantity_product_uom
            move = ml.move_id
            value = (move.value * ml.quantity / move.quantity) if 'value' in move._fields and move.quantity else 0.0
            amount = qty if self.measure == 'qty' else value
            if self.group_by == 'lot':
                key = (product.id, ml.lot_id.id or 0)
                keys[key] = (product.display_name, ml.lot_id.name or _('(no lot)'), product.uom_id.name)
            elif self.group_by == 'category':
                key = (product.categ_id.id, product.id)
                keys[key] = (product.categ_id.display_name, product.display_name, product.uom_id.name)
            else:
                key = (product.id,)
                keys[key] = (product.display_name, '', product.uom_id.name)
            d = data[key]
            if ml.date < start:
                if kind != 'internal':
                    d['opening'] += amount if kind in ('received', 'from_prod', 'other_in') else -amount
            else:
                d[kind] += amount
        for d in data.values():
            d['closing'] = d['opening'] + d['received'] + d['from_prod'] + d['other_in'] - d['issued'] - d['delivered'] - d['other_out']
        unit = self.measure == 'qty'
        lab = (_('Lot / Batch') if self.group_by == 'lot' else _('Item'))
        columns = [(_('Item') if self.group_by != 'category' else _('Item'), 't')]
        if self.group_by == 'lot':
            columns.append((lab, 'c'))
        if unit:
            columns.append((_('UoM'), 'c'))
        kind = 'q' if unit else 'n'
        columns += [(_('Opening'), kind), (_('Received (Purchase)'), kind), (_('From Production'), kind), (_('Other In'), kind),
                    (_('Issued to Production'), kind), (_('Delivered (Sales)'), kind), (_('Other Out'), kind),
                    (_('Closing'), kind), (_('Internal Transfers'), kind)]
        first = len(columns) - len(self.COLS)
        groups = defaultdict(list)
        for key in sorted(keys, key=lambda k: keys[k]):
            d = data[key]
            if self.hide_zero and all(abs(d[c]) < 0.0001 for c in self.COLS):
                continue
            name, extra, uom = keys[key]
            if self.group_by == 'category':
                row, group = [extra], name
            else:
                row, group = [name], ''
                if self.group_by == 'lot':
                    row.append(extra)
            if unit:
                row.append(uom)
            row += [d[c] for c in self.COLS]
            groups[group].append(row)
        out, grand = [], defaultdict(float)
        sum_ok = not unit  # quantities of different units are not added up
        for g, rows in groups.items():
            totals = {i: sum(r[i] for r in rows) for i in range(first, len(columns))} if sum_ok or len({r[first - 1] for r in rows}) == 1 else {}
            for i, v in totals.items():
                grand[i] += v
            out.append({'title': g or _('All items'), 'sub': _('Items: %s', len(rows)), 'rows': rows, 'totals': totals})
        filters = self._register_filter_lines()
        filters.append((_('Warehouse'), self.warehouse_id.name or _('All')))
        filters.append((_('Showing'), dict(self._fields['measure'].selection)[self.measure]))
        return {'title': _('Stock Movement Report'), 'filters': filters, 'columns': columns, 'groups': out,
                'totals': dict(grand) if sum_ok else {}}


class DeptStockWizard(models.TransientModel):
    """Department Stock & WIP: for each production department, every item -
    opening, issued from the store, received from the previous department,
    consumed, produced, transferred on (next department / store), waste,
    count adjustments, closing (material + work in process lying there)."""
    _name = 'combine.dept.stock.wizard'
    _inherit = 'combine.register.mixin'
    _description = 'Department Stock & WIP Report'
    _register_report_xmlid = 'combine_costing.action_report_dept_stock'

    department_ids = fields.Many2many('combine.production.department', 'combine_deptstock_dept_rel', 'wizard_id', 'dept_id',
                                      string='Departments', help='Leave empty for all.')
    measure = fields.Selection([('qty', 'Quantity'), ('value', 'Value')], required=True, default='qty')

    COLS = ('opening', 'issue', 'transfer_in', 'consume', 'produce', 'transfer_out', 'to_store', 'waste', 'adjust', 'closing')

    def _register_data(self):
        self.ensure_one()
        dom = [('company_id', '=', self.env.company.id), ('date', '<=', self.date_to)]
        if self.department_ids:
            dom.append(('department_id', 'in', self.department_ids.ids))
        data = defaultdict(lambda: defaultdict(float))
        field = 'qty' if self.measure == 'qty' else 'value'
        for row in self.env['combine.dept.ledger'].search(dom):
            if not self._register_product_ok(row.product_id):
                continue
            d = data[(row.department_id, row.product_id)]
            v = row[field]
            if row.date < self.date_from:
                d['opening'] += v
            else:
                d[row.kind] += abs(v) if row.kind not in ('adjust',) else v
        for (dept, product), d in data.items():
            d['closing'] = d['opening'] + d['issue'] + d['transfer_in'] - d['consume'] + d['produce'] - d['transfer_out'] \
                - d['to_store'] + d['waste'] + d['adjust']
        unit = self.measure == 'qty'
        kind = 'q' if unit else 'n'
        columns = [(_('Item'), 't')] + ([(_('UoM'), 'c')] if unit else []) + [
            (_('Opening'), kind), (_('Issued from Store'), kind), (_('From Department'), kind), (_('Consumed'), kind),
            (_('Produced'), kind), (_('To Next Dept.'), kind), (_('To Store'), kind), (_('Waste'), kind),
            (_('Count Adj.'), kind), (_('Closing (WIP)'), kind)]
        first = len(columns) - len(self.COLS)
        by_dept = defaultdict(list)
        for (dept, product) in sorted(data, key=lambda k: (k[0].sequence, k[0].name, k[1].display_name)):
            d = data[(dept, product)]
            if all(abs(d[c]) < 0.0001 for c in self.COLS):
                continue
            by_dept[dept].append([product.display_name] + ([product.uom_id.name] if unit else []) + [d[c] for c in self.COLS])
        groups, grand = [], defaultdict(float)
        for dept, rows in by_dept.items():
            totals = {i: sum(r[i] for r in rows) for i in range(first, len(columns))} if not unit else {}
            for i, v in totals.items():
                grand[i] += v
            groups.append({'title': dept.name, 'sub': '', 'rows': rows, 'totals': totals})
        filters = self._register_filter_lines()
        if self.department_ids:
            filters.append((_('Departments'), ', '.join(self.department_ids.mapped('name'))))
        filters.append((_('Showing'), dict(self._fields['measure'].selection)[self.measure]))
        return {'title': _('Department Stock & WIP Report'), 'filters': filters, 'columns': columns, 'groups': groups,
                'totals': dict(grand)}


class CostVarianceWizard(models.TransientModel):
    """Cost & Variance Analysis: actual against standard for completed
    production batches - material price variance, material usage variance,
    conversion variance - batch-wise, item-wise or department-wise, for any
    period. Positive = adverse (cost more than standard)."""
    _name = 'combine.cost.variance.wizard'
    _inherit = 'combine.register.mixin'
    _description = 'Cost & Variance Analysis'
    _register_report_xmlid = 'combine_costing.action_report_cost_variance'

    department_ids = fields.Many2many('combine.production.department', 'combine_costvar_dept_rel', 'wizard_id', 'dept_id',
                                      string='Departments', help='Leave empty for all.')
    group_by = fields.Selection([('batch', 'Batch-wise'), ('item', 'Item-wise'), ('department', 'Department-wise'),
                                 ('month', 'Month-wise')], required=True, default='batch')

    @staticmethod
    def _split(batch):
        price = sum((l.actual_price - l.std_price) * l.qty for l in batch.input_ids if l.qty > 0)
        material_var = batch.material_cost - batch.std_material
        return {'qty': batch.qty_produced, 'actual': batch.actual_cost, 'std': batch.std_cost, 'price': price,
                'usage': material_var - price, 'conversion': batch.conversion_actual - batch.conversion_std,
                'total': batch.variance}

    def _register_data(self):
        self.ensure_one()
        dom = [('company_id', '=', self.env.company.id), ('state', '=', 'done'),
               ('date', '>=', self.date_from), ('date', '<=', self.date_to)]
        if self.department_ids:
            dom.append(('department_id', 'in', self.department_ids.ids))
        batches = self.env['combine.production.batch'].search(dom, order='date, id').filtered(
            lambda b: self._register_product_ok(b.product_id))
        keys = ('qty', 'actual', 'std', 'price', 'usage', 'conversion', 'total')
        columns = [(_('Batch / Item'), 't'), (_('Output Qty'), 'q'), (_('UoM'), 'c'), (_('Actual Cost'), 'n'),
                   (_('Standard Cost'), 'n'), (_('Material Price Var.'), 'n'), (_('Material Usage Var.'), 'n'),
                   (_('Conversion Var.'), 'n'), (_('Total Variance'), 'n'), (_('Var. %'), 'c'),
                   (_('Actual / Unit'), 'n'), (_('Std. / Unit'), 'n')]

        def row(label, uom, s):
            pct = (s['total'] / s['std'] * 100) if s['std'] else 0.0
            return [label, s['qty'], uom, s['actual'], s['std'], s['price'], s['usage'], s['conversion'], s['total'],
                    f'{pct:,.1f}%' if s['std'] else '-', s['actual'] / s['qty'] if s['qty'] else 0.0,
                    s['std'] / s['qty'] if s['qty'] else 0.0]

        groups = []
        if self.group_by == 'batch':
            by_dept = defaultdict(list)
            for b in batches:
                by_dept[b.department_id].append(b)
            for dept, bs in by_dept.items():
                rows = [row('%s  %s  %s' % (b.name, fields.Date.to_string(b.date), b.product_id.display_name), b.uom_id.name,
                            self._split(b)) for b in bs]
                groups.append({'title': dept.name, 'sub': _('Batches: %s', len(rows)), 'rows': rows,
                               'totals': {i: sum(r[i] for r in rows) for i in (3, 4, 5, 6, 7, 8)}})
        else:
            agg = defaultdict(lambda: defaultdict(float))
            label = {}
            for b in batches:
                if self.group_by == 'item':
                    k = (b.department_id.name, b.product_id.display_name, b.uom_id.name)
                elif self.group_by == 'department':
                    k = ('', b.department_id.name, b.uom_id.name)
                else:
                    k = ('', b.date.strftime('%Y-%m') + '  ' + b.department_id.name, b.uom_id.name)
                for key, v in self._split(b).items():
                    agg[k][key] += v
            by_group = defaultdict(list)
            for k in sorted(agg):
                by_group[k[0]].append(row(k[1], k[2], agg[k]))
            for g, rows in by_group.items():
                groups.append({'title': g or _('Summary'), 'sub': '', 'rows': rows,
                               'totals': {i: sum(r[i] for r in rows) for i in (3, 4, 5, 6, 7, 8)}})
        grand = {i: sum(g['totals'][i] for g in groups) for i in (3, 4, 5, 6, 7, 8)} if groups else {}
        filters = self._register_filter_lines()
        if self.department_ids:
            filters.append((_('Departments'), ', '.join(self.department_ids.mapped('name'))))
        filters.append((_('Variance'), _('positive = adverse (above standard), negative = favourable')))
        open_close = batches.filtered(lambda b: not b.closed_period_id)
        if open_close:
            filters.append((_('Note'), _('%s batches not yet in a month-end cost close: conversion at standard', len(open_close))))
        return {'title': _('Cost & Variance Analysis'), 'filters': filters, 'columns': columns, 'groups': groups, 'totals': grand}
