"""Production reports (house-style PDF / Excel via Custom Reports' register engine):

* Production Entries  - every production order, line by line
* Daily Production    - per day: items produced, quantity, rate, value
* Total Production    - totals per item (and/or unit, category) for the period
Same wizard, different defaults; every grouping / filter is available in all three."""
from collections import OrderedDict

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import format_date

KINDS = [('entries', 'Production Entries'), ('daily', 'Daily Production'), ('total', 'Total Production')]
NUM = ('qty', 'value', 'count')


class ProductionReport(models.TransientModel):
    _name = 'combine.prod.report'
    _inherit = 'combine.register.mixin'
    _description = 'Production report'
    _register_report_xmlid = 'combine_production.action_report_production'

    report_kind = fields.Selection(KINDS, required=True, default='entries')
    by_date = fields.Boolean(string='By Date')
    by_unit = fields.Boolean(string='By Production Unit')
    by_categ = fields.Boolean(string='By Item Category')
    by_item = fields.Boolean(string='By Item')
    detail = fields.Selection([('detail', 'Every production entry'), ('summary', 'Summary (one line per group)')],
                              required=True, default='detail')
    warehouse_ids = fields.Many2many('stock.warehouse', 'combine_prodrep_wh_rel', 'wizard_id', 'warehouse_id',
                                     string='Production Units', help='Leave empty for all units.')
    user_ids = fields.Many2many('res.users', 'combine_prodrep_user_rel', 'wizard_id', 'user_id',
                                string='Entered by', help='Leave empty for all users.')
    # the mixin's own relations would be named after this model - keep them short and explicit
    partner_ids = fields.Many2many('res.partner', 'combine_prodrep_partner_rel', 'wizard_id', 'partner_id', string='Parties')
    party_type_ids = fields.Many2many('combine.party.type', 'combine_prodrep_ptype_rel', 'wizard_id', 'type_id', string='Party Types')
    product_ids = fields.Many2many('product.product', 'combine_prodrep_product_rel', 'wizard_id', 'product_id', string='Items')
    categ_ids = fields.Many2many('product.category', 'combine_prodrep_categ_rel', 'wizard_id', 'categ_id', string='Item Categories')

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        kind = vals.get('report_kind') or 'entries'
        vals.update({
            'entries': {'detail': 'detail', 'by_date': True, 'by_item': False, 'by_unit': False},
            'daily': {'detail': 'summary', 'by_date': True, 'by_item': True, 'by_unit': False},
            'total': {'detail': 'summary', 'by_date': False, 'by_item': True, 'by_unit': False},
        }[kind])
        return vals

    # ------------------------------------------------------------ data
    def _lines(self):
        start = fields.Datetime.to_datetime(self.date_from)
        end = fields.Datetime.to_datetime(self.date_to).replace(hour=23, minute=59, second=59)
        domain = [('state', '=', 'done'), ('company_id', '=', self.env.company.id),
                  ('date_finished', '>=', start), ('date_finished', '<=', end)]
        if self.warehouse_ids:
            domain.append(('picking_type_id.warehouse_id', 'in', self.warehouse_ids.ids))
        if self.user_ids:
            domain.append(('create_uid', 'in', self.user_ids.ids))
        out = []
        for mo in self.env['mrp.production'].sudo().search(domain, order='date_finished, name'):
            if not self._register_product_ok(mo.product_id):
                continue
            finished = mo.move_finished_ids.filtered(lambda m: m.state == 'done' and m.product_id == mo.product_id)
            qty = sum(m.product_uom._compute_quantity(m.quantity, mo.product_id.uom_id) for m in finished)
            value = sum(finished.mapped('value'))
            day = fields.Datetime.context_timestamp(self, mo.date_finished).date()
            out.append({
                'date': day, 'date_key': str(day), 'date_label': format_date(self.env, day, date_format='dd-MMM-yy'),
                'mo': mo.name, 'unit': mo.picking_type_id.warehouse_id.name or '',
                'categ': mo.product_id.categ_id.display_name or '', 'item': mo.product_id.display_name,
                'uom': mo.product_id.uom_id.name, 'qty': qty, 'rate': (value / qty) if qty else mo.x_unit_cost,
                'value': value, 'user': mo.create_uid.name or '', 'count': 1,
            })
        return out

    def _dims(self):
        dims = []
        if self.by_date:
            dims.append(('date_label', _('Date')))
        if self.by_unit:
            dims.append(('unit', _('Unit')))
        if self.by_categ:
            dims.append(('categ', _('Category')))
        if self.by_item:
            dims.append(('item', _('Item')))
        return dims

    def _columns(self, dims):
        keys = [d[0] for d in dims]
        if self.detail == 'detail':
            cols = []
            if 'date_label' not in keys:
                cols.append((_('Date'), 'd', 'date'))
            cols.append((_('Production Order'), 't', 'mo'))
            for key, label in (('unit', _('Unit')), ('item', _('Item'))):
                if key not in keys:
                    cols.append((label, 't', key))
            cols += [(_('UoM'), 'c', 'uom'), (_('Quantity'), 'q', 'qty'), (_('Unit Cost'), 'n', 'rate'),
                     (_('Value'), 'n', 'value'), (_('Entered by'), 't', 'user')]
            return cols
        rest = dims[1:] if len(dims) > 1 else dims
        cols = [(label, 't', key) for key, label in rest]
        cols += [(_('Entries'), 'c', 'count'), (_('UoM'), 'c', 'uom'), (_('Quantity'), 'q', 'qty'),
                 (_('Avg Unit Cost'), 'n', 'rate'), (_('Min Rate'), 'n', 'min_rate'), (_('Max Rate'), 'n', 'max_rate'),
                 (_('Value'), 'n', 'value')]
        return cols

    @staticmethod
    def _summarise(rows):
        out = {k: sum(r[k] for r in rows) for k in NUM}
        uoms = sorted({r['uom'] for r in rows if r['uom']})
        out['uom'] = ', '.join(uoms)
        if len(uoms) > 1:
            out['qty'] = None
        rates = [r['rate'] for r in rows if r['qty']]
        out['rate'] = (out['value'] / out['qty']) if out['qty'] else None
        out['min_rate'] = min(rates) if rates else None
        out['max_rate'] = max(rates) if rates else None
        return out

    @staticmethod
    def _group(rows, keys):
        out = OrderedDict()
        for r in sorted(rows, key=lambda r: tuple(r['date_key'] if k == 'date_label' else str(r[k]) for k in keys)):
            out.setdefault(tuple(r[k] for k in keys), []).append(r)
        return out

    def _register_data(self):
        self.ensure_one()
        dims = self._dims()
        if self.detail == 'summary' and not dims:
            raise UserError(_('Tick at least one "By ..." option for a summary.'))
        cols = self._columns(dims)
        keys = [c[2] for c in cols]
        lines = self._lines()

        def as_row(r):
            return [r.get(k) if r.get(k) is not None else ('' if k not in NUM + ('rate', 'min_rate', 'max_rate') else None)
                    for k in keys]

        def totals(rows):
            s = self._summarise(rows) if rows else {}
            return {i: s[k] for i, k in enumerate(keys) if k in NUM and s.get(k) is not None}

        groups = []
        if self.detail == 'detail':
            for key, rows in (self._group(lines, [d[0] for d in dims]).items() if dims else [((), lines)]):
                if not rows:
                    continue
                groups.append({'title': ' > '.join(str(k) for k in key) if key else _('All production'),
                               'sub': _('%s entr(ies)', len(rows)), 'rows': [as_row(r) for r in rows],
                               'totals': totals(rows)})
        else:
            first, rest = dims[0][0], [d[0] for d in dims[1:]]
            if not rest:
                # one compact table: a line per date / unit / item
                rows_all = []
                for name, rows in self._group(lines, [first]).items():
                    vals = self._summarise(rows)
                    vals[first] = name[0]
                    rows_all.append(as_row(vals))
                if rows_all:
                    groups = [{'title': dims[0][1], 'sub': _('%s line(s)', len(rows_all)),
                               'rows': rows_all, 'totals': totals(lines)}]
            else:
                # a block per first grouping (e.g. per day), a line per the rest (e.g. per item)
                for name, rows in self._group(lines, [first]).items():
                    sub = []
                    for key, part in self._group(rows, rest).items():
                        vals = self._summarise(part)
                        vals.update(dict(zip(rest, key)))
                        sub.append(vals)
                    groups.append({'title': name[0], 'sub': _('%s line(s)', len(sub)),
                                   'rows': [as_row(r) for r in sub], 'totals': totals(rows)})
        filters = self._register_filter_lines()
        for label, recs in ((_('Production Units'), self.warehouse_ids), (_('Entered by'), self.user_ids)):
            if recs:
                filters.append((label, ', '.join(recs.mapped('display_name'))))
        filters.append((_('Grouped by'), ' > '.join(l for _k, l in dims) or _('none')))
        return {'title': dict(KINDS)[self.report_kind], 'filters': filters,
                'columns': [(c[0], c[1]) for c in cols], 'groups': groups,
                'totals': totals(lines) if groups else {}}
