"""Delivery Cost report: what each delivery (challan) cost, and from which stock under FIFO -
e.g. production 1 used up + part of production 2 - with quantity, rate and cost per batch.
Optional sale value and margin. House-style PDF / Excel via Custom Reports' register engine."""
from collections import OrderedDict

from odoo import _, fields, models
from odoo.tools import format_date

NUM = ('qty', 'cost', 'sale', 'margin', 'src_qty')


class DeliveryCostReport(models.TransientModel):
    _name = 'combine.delivery.cost'
    _inherit = 'combine.register.mixin'
    _description = 'Delivery cost report'
    _register_report_xmlid = 'combine_production.action_report_delivery_cost'

    detail = fields.Selection([('split', 'Cost split by production / stock batch'),
                               ('line', 'One line per item delivered')], required=True, default='split')
    group_by = fields.Selection([('delivery', 'Delivery'), ('customer', 'Customer'), ('item', 'Item'),
                                 ('none', 'No grouping')], required=True, default='delivery')
    show_sale = fields.Boolean(string='Show sale value & margin', default=True)
    include_returns = fields.Boolean(string='Include customer returns', default=True,
                                     help='Returns from customers are shown as negatives.')
    warehouse_ids = fields.Many2many('stock.warehouse', 'combine_delcost_wh_rel', 'wizard_id', 'warehouse_id',
                                     string='Units / Warehouses', help='Leave empty for all.')
    partner_ids = fields.Many2many('res.partner', 'combine_delcost_partner_rel', 'wizard_id', 'partner_id', string='Customers')
    party_type_ids = fields.Many2many('combine.party.type', 'combine_delcost_ptype_rel', 'wizard_id', 'type_id', string='Party Types')
    product_ids = fields.Many2many('product.product', 'combine_delcost_product_rel', 'wizard_id', 'product_id', string='Items')
    categ_ids = fields.Many2many('product.category', 'combine_delcost_categ_rel', 'wizard_id', 'categ_id', string='Item Categories')

    # ------------------------------------------------------------ data
    def _moves(self):
        start = fields.Datetime.to_datetime(self.date_from)
        end = fields.Datetime.to_datetime(self.date_to).replace(hour=23, minute=59, second=59)
        domain = [('state', '=', 'done'), ('company_id', '=', self.env.company.id), ('date', '>=', start), ('date', '<=', end),
                  ('picking_id', '!=', False)]
        if self.include_returns:
            domain += ['|', '&', ('location_dest_id.usage', '=', 'customer'), ('location_id.usage', '=', 'internal'),
                       '&', ('location_id.usage', '=', 'customer'), ('location_dest_id.usage', '=', 'internal')]
        else:
            domain += [('location_dest_id.usage', '=', 'customer'), ('location_id.usage', '=', 'internal')]
        if self.warehouse_ids:
            domain.append(('picking_id.picking_type_id.warehouse_id', 'in', self.warehouse_ids.ids))
        return self.env['stock.move'].sudo().search(domain, order='date, id')

    def _lines(self):
        out = []
        for move in self._moves():
            partner = move.picking_id.partner_id or move.partner_id
            if not self._register_partner_ok(partner) or not self._register_product_ok(move.product_id):
                continue
            sign = -1.0 if move.location_id.usage == 'customer' else 1.0
            qty = move.product_uom._compute_quantity(move.quantity, move.product_id.uom_id) * sign
            cost = abs(move.value) * sign
            sale = None
            sl = move.sale_line_id
            if sl and sl.product_uom_qty:
                sale_rate = sl.price_subtotal / sl.product_uom_qty  # excl. tax, per sale UoM
                sale = sale_rate * move.product_uom._compute_quantity(move.quantity, sl.product_uom_id) * sign
            day = fields.Datetime.context_timestamp(self, move.date).date()
            base = {
                'date': day, 'date_key': str(day), 'delivery': move.picking_id.name,
                'delivery_title': '%s  |  %s  |  %s' % (move.picking_id.name, format_date(self.env, day, date_format='dd-MMM-yy'),
                                                        partner.commercial_partner_id.name or ''),
                'customer': partner.commercial_partner_id.name or '', 'item': move.product_id.display_name,
                'uom': move.product_id.uom_id.name, 'order': sl.order_id.name if sl else (move.origin or ''),
                'qty': qty, 'cost': cost, 'avg_cost': (cost / qty) if qty else 0.0,
                'sale': sale, 'margin': (sale - cost) if sale is not None else None,
                'sale_rate': (sale / qty) if qty and sale is not None else None,
            }
            allocs = move.x_fifo_allocation_ids.sorted('sequence')
            if allocs:
                pieces = [{'source': a._source_label(),
                           'src_date': fields.Datetime.context_timestamp(self, a.in_move_id.date).date() if a.in_move_id else None,
                           'src_qty': a.quantity * sign, 'rate': a.unit_cost, 'src_cost': a.value * sign} for a in allocs]
            elif move.location_id.usage == 'customer':
                pieces = [{'source': _('Customer return (cost of original delivery)'), 'src_date': None,
                           'src_qty': qty, 'rate': (cost / qty) if qty else 0.0, 'src_cost': cost}]
            else:
                pieces = [{'source': _('No batch split (%s costing)', move.product_id.cost_method), 'src_date': None,
                           'src_qty': qty, 'rate': (cost / qty) if qty else 0.0, 'src_cost': cost}]
            base['pieces'] = pieces
            out.append(base)
        return out

    def _columns(self):
        g = self.group_by
        cols = []
        if g != 'delivery':
            cols += [(_('Date'), 'd', 'date'), (_('Delivery'), 't', 'delivery')]
            if g != 'customer':
                cols.append((_('Customer'), 't', 'customer'))
        if g != 'item':
            cols.append((_('Item'), 't', 'item'))
        cols += [(_('UoM'), 'c', 'uom'), (_('Qty'), 'q', 'qty')]
        if self.detail == 'split':
            cols += [(_('Taken from'), 't', 'source'), (_('Batch Date'), 'd', 'src_date'), (_('Batch Qty'), 'q', 'src_qty'),
                     (_('Rate'), 'n', 'rate'), (_('Cost'), 'n', 'cost')]
        else:
            cols += [(_('Avg Cost'), 'n', 'avg_cost'), (_('Cost'), 'n', 'cost')]
        if self.show_sale:
            cols += [(_('Sale Rate'), 'n', 'sale_rate'), (_('Sale Value'), 'n', 'sale'), (_('Margin'), 'n', 'margin')]
        return cols

    def _rows(self, line, keys):
        """One row per delivered item, or (split) one row per FIFO batch - item columns on the first only."""
        def cell(src, k):
            v = src.get(k)
            return v if v is not None else ('' if k not in NUM + ('rate', 'avg_cost', 'sale_rate') else None)
        if self.detail != 'split':
            return [[cell(line, k) for k in keys]]
        rows = []
        for i, piece in enumerate(line['pieces']):
            src = dict(line) if i == 0 else {}
            src.update({'source': piece['source'], 'src_date': piece['src_date'], 'src_qty': piece['src_qty'],
                        'rate': piece['rate'], 'cost': piece['src_cost']})
            if i:
                src.update({'qty': None, 'sale': None, 'margin': None, 'sale_rate': None})
            rows.append([cell(src, k) for k in keys])
        return rows

    def _register_data(self):
        self.ensure_one()
        cols = self._columns()
        keys = [c[2] for c in cols]
        lines = self._lines()

        def totals(rows):
            tot = {}
            for i, k in enumerate(keys):
                if k in ('qty', 'cost', 'sale', 'margin', 'src_qty'):
                    src = 'qty' if k == 'src_qty' else k
                    tot[i] = sum(r[src] or 0.0 for r in rows)
            return tot

        key_fn = {'delivery': lambda l: (l['date_key'], l['delivery']), 'customer': lambda l: l['customer'],
                  'item': lambda l: l['item'], 'none': lambda l: ''}[self.group_by]
        title_fn = {'delivery': lambda l: l['delivery_title'], 'customer': lambda l: l['customer'],
                    'item': lambda l: l['item'], 'none': lambda l: _('All deliveries')}[self.group_by]
        buckets = OrderedDict()
        for line in sorted(lines, key=lambda l: (key_fn(l), l['date_key'], l['delivery'])):
            buckets.setdefault(key_fn(line), []).append(line)
        groups = []
        for _key, rows in buckets.items():
            body = []
            for line in rows:
                body += self._rows(line, keys)
            groups.append({'title': title_fn(rows[0]), 'sub': _('%s item line(s)', len(rows)), 'rows': body,
                           'totals': totals(rows)})
        filters = self._register_filter_lines()
        if self.warehouse_ids:
            filters.append((_('Units / Warehouses'), ', '.join(self.warehouse_ids.mapped('name'))))
        filters.append((_('Grouped by'), dict(self._fields['group_by'].selection)[self.group_by]))
        if not self.include_returns:
            filters.append((_('Customer returns'), _('excluded')))
        return {'title': _('Delivery Cost Report'), 'filters': filters, 'columns': [(c[0], c[1]) for c in cols],
                'groups': groups, 'totals': totals(lines) if groups else {}}
