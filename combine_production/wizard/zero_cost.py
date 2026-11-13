"""Zero-Cost Stock report: what is in stock at cost 0 (with the document it came in on) and what was
delivered / consumed at cost 0 (with challan, customer, date). House-style PDF / Excel."""
from collections import OrderedDict

from odoo import _, fields, models

NUM = ('qty', 'zero_qty')


class ZeroCostReport(models.TransientModel):
    _name = 'combine.zero.cost'
    _inherit = 'combine.register.mixin'
    _description = 'Zero-cost stock report'
    _register_report_xmlid = 'combine_production.action_report_zero_cost'

    section = fields.Selection([('both', 'Available at 0 and sold / consumed at 0'), ('available', 'Available at 0 only'),
                                ('sold', 'Sold / consumed at 0 only')], required=True, default='both')
    group_by = fields.Selection([('item', 'Item'), ('reference', 'Document')], required=True, default='item')
    out_kind = fields.Selection([('all', 'All'), ('delivery', 'Deliveries'), ('consumption', 'Consumption'),
                                 ('adjustment', 'Adjustments')], string='Sold / consumed', required=True, default='all')
    warehouse_ids = fields.Many2many('stock.warehouse', 'combine_zerocost_wh_rel', 'wizard_id', 'warehouse_id',
                                     string='Warehouses', help='Leave empty for all.')
    partner_ids = fields.Many2many('res.partner', 'combine_zerocost_partner_rel', 'wizard_id', 'partner_id', string='Customers')
    party_type_ids = fields.Many2many('combine.party.type', 'combine_zerocost_ptype_rel', 'wizard_id', 'type_id', string='Party Types')
    product_ids = fields.Many2many('product.product', 'combine_zerocost_product_rel', 'wizard_id', 'product_id', string='Items')
    categ_ids = fields.Many2many('product.category', 'combine_zerocost_categ_rel', 'wizard_id', 'categ_id', string='Item Categories')
    date_from = fields.Date(string='Sold from', required=True, default=lambda s: fields.Date.context_today(s).replace(month=1, day=1))

    # ------------------------------------------------------------ helpers
    def _ref(self, move):
        return move.picking_id.name or move.production_id.name or move.raw_material_production_id.name or move.reference or ''

    def _day(self, dt):
        return fields.Datetime.context_timestamp(self, dt).date() if dt else None

    def _wh_ok(self, move):
        if not self.warehouse_ids:
            return True
        wh = move.picking_type_id.warehouse_id or move.location_id.warehouse_id or move.location_dest_id.warehouse_id
        return wh in self.warehouse_ids

    def _products(self):
        domain = [('is_storable', '=', True), ('company_id', 'in', [False, self.env.company.id])]
        if self.product_ids:
            domain.append(('id', 'in', self.product_ids.ids))
        if self.categ_ids:
            domain.append(('categ_id', 'child_of', self.categ_ids.ids))
        return self.env['product.product'].with_context(active_test=False).search(domain)

    # ------------------------------------------------------------ available at 0
    def _available_rows(self):
        rows = []
        Move = self.env['stock.move'].sudo()
        products = self._products().filtered(lambda p: p.qty_available > 0)
        fifo = products.filtered(lambda p: p.cost_method == 'fifo')
        remaining = fifo._get_remaining_moves() if fifo else {}
        for product in fifo:
            for move, qty in remaining.get(product, {}).items():
                if qty <= 0 or not move.company_id.currency_id.is_zero(move.value) or not self._wh_ok(move):
                    continue
                rows.append(self._row('available', move, product, move._get_valued_qty(), qty))
        for product in products - fifo:
            if product.standard_price:
                continue
            on_hand = product.qty_available
            # the latest zero-valued receipts explain what is on hand at 0
            for move in Move.search([('product_id', '=', product.id), ('state', '=', 'done'), ('is_in', '=', True),
                                     ('company_id', '=', self.env.company.id)], order='date desc, id desc'):
                if on_hand <= 0:
                    break
                qty = move._get_valued_qty()
                part = min(qty, on_hand)
                on_hand -= part
                if self._wh_ok(move):
                    rows.append(self._row('available', move, product, qty, part))
        return rows

    # ------------------------------------------------------------ sold / consumed at 0
    def _sold_rows(self):
        rows = []
        start = fields.Datetime.to_datetime(self.date_from)
        end = fields.Datetime.to_datetime(self.date_to).replace(hour=23, minute=59, second=59)
        products = self._products()
        domain = [('state', '=', 'done'), ('is_out', '=', True), ('company_id', '=', self.env.company.id),
                  ('product_id', 'in', products.ids), ('date', '>=', start), ('date', '<=', end), ('quantity', '>', 0)]
        Move = self.env['stock.move'].sudo()
        zero_moves = Move.search(domain + [('value', '=', 0)], order='date, id')
        # FIFO deliveries partly taken from zero-cost batches
        allocs = self.env['combine.fifo.allocation'].sudo().search([
            ('out_move_id', 'in', Move.search(domain + [('value', '!=', 0)]).ids), ('value', '=', 0), ('quantity', '>', 0)])
        for move in zero_moves | allocs.out_move_id:
            if not self._wh_ok(move) or not self._kind_ok(move):
                continue
            partner = move.picking_id.partner_id or move.partner_id
            if (self.partner_ids or self.party_type_ids) and not (partner and self._register_partner_ok(partner)):
                continue
            pieces = move.x_fifo_allocation_ids.filtered(lambda a: move.company_id.currency_id.is_zero(a.value))
            qty = move._get_valued_qty()
            if pieces:
                for a in pieces:
                    rows.append(self._row('sold', move, move.product_id, qty, a.quantity, source=a._source_label()))
            elif move.company_id.currency_id.is_zero(move.value):
                rows.append(self._row('sold', move, move.product_id, qty, qty, source=''))
        return rows

    def _kind_ok(self, move):
        if self.out_kind == 'all':
            return True
        label = move._combine_kind_label()
        return {'delivery': _('Delivery'), 'consumption': _('Consumption'), 'adjustment': _('Adjustment')}[self.out_kind] == label

    def _row(self, section, move, product, qty, zero_qty, source=None):
        partner = move.picking_id.partner_id or move.partner_id
        return {
            'section': section, 'date': self._day(move.date), 'date_key': str(move.date), 'reference': self._ref(move),
            'type': _('Received at 0') if section == 'available' else move._combine_kind_label(),
            'party': partner.commercial_partner_id.name or '', 'item': product.display_name,
            'uom': product.uom_id.name, 'qty': qty, 'zero_qty': zero_qty,
            'source': source if source is not None else (move.origin or ''),
            'warehouse': (move.picking_type_id.warehouse_id or move.location_dest_id.warehouse_id
                          or move.location_id.warehouse_id).name or '',
        }

    # ------------------------------------------------------------ layout
    def _columns(self):
        cols = [(_('Date'), 'd', 'date')]
        if self.group_by != 'reference':
            cols.append((_('Document'), 't', 'reference'))
        cols += [(_('Type'), 'c', 'type'), (_('Customer / Party'), 't', 'party')]
        if self.group_by != 'item':
            cols.append((_('Item'), 't', 'item'))
        cols += [(_('Warehouse'), 't', 'warehouse'), (_('UoM'), 'c', 'uom'), (_('Document Qty'), 'q', 'qty'),
                 (_('Qty at Cost 0'), 'q', 'zero_qty'), (_('Source / Origin'), 't', 'source')]
        return cols

    def _register_data(self):
        self.ensure_one()
        cols = self._columns()
        keys = [c[2] for c in cols]
        data = []
        if self.section in ('both', 'available'):
            data += self._available_rows()
        if self.section in ('both', 'sold'):
            data += self._sold_rows()
        titles = {'available': _('AVAILABLE AT COST 0'), 'sold': _('SOLD / CONSUMED AT COST 0')}
        key = (lambda r: (r['section'], r['item'])) if self.group_by == 'item' else (lambda r: (r['section'], r['reference']))
        buckets = OrderedDict()
        for r in sorted(data, key=lambda r: (0 if r['section'] == 'available' else 1,) + key(r)[1:] + (r['date_key'],)):
            buckets.setdefault(key(r), []).append(r)
        groups = []
        zi = keys.index('zero_qty')
        for (section, name), rows in buckets.items():
            groups.append({'title': '%s  |  %s' % (titles[section], name), 'sub': _('%s line(s)', len(rows)),
                           'rows': [[r.get(k) if r.get(k) is not None else '' for k in keys] for r in rows],
                           'totals': {zi: sum(r['zero_qty'] for r in rows)}})
        filters = self._register_filter_lines()
        if self.warehouse_ids:
            filters.append((_('Warehouses'), ', '.join(self.warehouse_ids.mapped('name'))))
        filters.append((_('Showing'), dict(self._fields['section'].selection)[self.section]))
        if self.section != 'available':
            filters.append((_('Out type'), dict(self._fields['out_kind'].selection)[self.out_kind]))
        avail = sum(r['zero_qty'] for r in data if r['section'] == 'available')
        sold = sum(r['zero_qty'] for r in data if r['section'] == 'sold')
        filters.append((_('Totals'), _('available at 0: %(a)s  |  sold / consumed at 0: %(s)s',
                                       a='{:,.2f}'.format(avail), s='{:,.2f}'.format(sold))))
        return {'title': _('Zero-Cost Stock Report'), 'filters': filters, 'columns': [(c[0], c[1]) for c in cols],
                'groups': groups, 'totals': {}}
