"""Pending Contracts report (Sales > Reporting).

Per contract line: contract quantity, rate, value excl. / incl. GST, GST,
commission, delivered, pending delivery, invoiced, delivered-not-invoiced
and the values still pending - optionally with every delivery challan
underneath (delivered on that challan, invoiced against it, still to
invoice). Contract-wise or party-wise; one line per contract, item lines,
or items with each delivery. Read-only: it changes nothing.

Rendered by Custom Reports' register engine (house-style PDF + Excel).
"""
from collections import OrderedDict, defaultdict

from odoo import _, fields, models

EPS = 0.0001


class PendingContractsWizard(models.TransientModel):
    _name = 'combine.pending.contracts.wizard'
    _inherit = 'combine.register.mixin'
    _description = 'Pending Contracts'
    _register_report_xmlid = 'combine_commission.action_report_pending_contracts'

    date_from = fields.Date(string='Contracts from', required=True,
                            default=lambda self: fields.Date.context_today(self).replace(month=1, day=1))
    date_to = fields.Date(string='Contracts to', required=True, default=fields.Date.context_today)
    layout = fields.Selection([('document', 'Contract-wise'), ('party', 'Party-wise')],
                              string='Layout', required=True, default='document')
    detail = fields.Selection([
        ('summary', 'One line per contract'),
        ('lines', 'Contract items'),
        ('deliveries', 'Contract items with each delivery challan'),
    ], string='Detail', required=True, default='lines')
    show = fields.Selection([
        ('open', 'Open - pending delivery or delivered but not invoiced'),
        ('delivery', 'Pending delivery only'),
        ('invoice', 'Delivered but not invoiced only'),
        ('all', 'All contracts (including completed)'),
    ], string='Show', required=True, default='open')
    order_ids = fields.Many2many('sale.order', 'combine_pend_order_rel', 'wizard_id', 'order_id', string='Contracts',
                                 domain=[('state', '=', 'sale')], help='Leave empty for all contracts.')
    agent_ids = fields.Many2many('combine001.commission.agent', 'combine_pend_agent_rel', 'wizard_id', 'agent_id',
                                 string='Commission Agents', help='Leave empty for all (with or without agent).')
    tax_ids = fields.Many2many('account.tax', 'combine_pend_tax_rel', 'wizard_id', 'tax_id', string='Tax Rates',
                               domain=[('type_tax_use', '=', 'sale')], help='Leave empty for all tax rates.')
    user_ids = fields.Many2many('res.users', 'combine_pend_user_rel', 'wizard_id', 'user_id', string='Salespersons',
                                help='Leave empty for all salespersons.')

    # ------------------------------------------------------------ figures
    def _line_figures(self, line):
        order = line.order_id
        qty = line.product_uom_qty
        delivered = line.qty_delivered
        invoiced = line.qty_invoiced
        pending, cancelled = self.env['combine.order.status.wizard']._order_line_balance(line, qty, delivered)
        uninvoiced = max(delivered - invoiced, 0.0)
        agent = order.commission_agent_id
        comm_pct = (order.commission_rate or agent.default_rate) if agent else 0.0
        base = order.commission_base or agent.default_base if agent else False
        commission = ((qty if base == 'quantity' else line.price_subtotal) * comm_pct / 100.0) if agent else 0.0
        unit_incl = line.price_total / qty if qty else 0.0
        return {
            'item': line.product_id.display_name, 'uom': line.product_uom_id.name, 'qty': qty,
            'rate': line.price_unit, 'ex': line.price_subtotal,
            'gst_pct': ', '.join('{:g}%'.format(t.amount) for t in line.tax_ids) or '-',
            'gst': line.price_tax, 'incl': line.price_total,
            'comm_pct': '{:g}%'.format(comm_pct) if agent else '', 'comm': commission,
            'delivered': delivered, 'pending': pending, 'invoiced': invoiced, 'uninvoiced': uninvoiced,
            'pending_val': pending * unit_incl, 'uninv_val': uninvoiced * unit_incl, 'cancelled': cancelled,
        }

    def _delivery_rows(self, line):
        """One row per validated delivery challan of this contract line:
        delivered on it, invoiced against it (invoices made from the challan
        first, other invoices matched to the oldest open challan), balance."""
        uom = line.product_uom_id
        per = OrderedDict()
        moves = line.move_ids.filtered(lambda m: m.state == 'done' and m.picking_id).sorted(
            lambda m: (m.date or fields.Datetime.now(), m.id))
        for move in moves:
            qty = move.product_uom._compute_quantity(move.quantity, uom)
            if move.origin_returned_move_id or move.location_dest_id.usage == 'internal':
                qty = -qty
            per.setdefault(move.picking_id, 0.0)
            per[move.picking_id] += qty
        has_link = 'x_delivery_challan_id' in self.env['account.move']._fields
        linked, free = defaultdict(float), 0.0
        for il in line.invoice_lines.filtered(lambda l: l.move_id.state == 'posted'):
            q = il.product_uom_id._compute_quantity(il.quantity, uom) if il.product_uom_id else il.quantity
            if il.move_id.move_type == 'out_refund':
                q = -q
            challan = il.move_id.x_delivery_challan_id if has_link else False
            if challan and challan in per:
                linked[challan] += q
            else:
                free += q
        unit_incl = line.price_total / line.product_uom_qty if line.product_uom_qty else 0.0
        rows = []
        for picking, delivered in per.items():
            inv = linked[picking]
            if free > EPS:
                take = min(max(delivered - inv, 0.0), free)
                inv += take
                free -= take
            date = picking.date_done.date() if picking.date_done else False
            label = '↳ %s  %s' % (picking.name, date.strftime('%d-%b-%y') if date else '')
            rows.append({'item': label, 'delivered': delivered, 'invoiced': inv,
                         'uninvoiced': max(delivered - inv, 0.0), 'uninv_val': max(delivered - inv, 0.0) * unit_incl,
                         '_delivery': True})
        return rows

    def _line_wanted(self, f):
        if self.show == 'delivery':
            return f['pending'] > EPS
        if self.show == 'invoice':
            return f['uninvoiced'] > EPS
        if self.show == 'open':
            return f['pending'] > EPS or f['uninvoiced'] > EPS
        return True

    def _orders(self):
        domain = [('company_id', '=', self.env.company.id), ('state', '=', 'sale'),
                  '|', '&', ('x_document_date', '>=', self.date_from), ('x_document_date', '<=', self.date_to),
                  '&', '&', ('x_document_date', '=', False),
                  ('date_order', '>=', fields.Datetime.to_datetime(self.date_from)),
                  ('date_order', '<', fields.Datetime.add(fields.Datetime.to_datetime(self.date_to), days=1))]
        if self.order_ids:
            domain.append(('id', 'in', self.order_ids.ids))
        if self.agent_ids:
            domain.append(('commission_agent_id', 'in', self.agent_ids.ids))
        if self.user_ids:
            domain.append(('user_id', 'in', self.user_ids.ids))
        orders = self.env['sale.order'].search(domain)
        return orders.filtered(lambda o: self._register_partner_ok(o.partner_id)).sorted(
            lambda o: (o._document_date(), o.id))

    # ------------------------------------------------------------ columns
    def _columns(self):
        cols = []
        if self.layout == 'party' or self.detail == 'summary':
            cols += [(_('Contract'), 't', 'contract'), (_('Date'), 'd', 'date')]
            if self.layout == 'document':
                cols.append((_('Customer'), 't', 'customer'))
        if self.detail != 'summary':
            cols += [(_('Item'), 't', 'item'), (_('UoM'), 'c', 'uom')]
        cols.append((_('Contract Qty'), 'q', 'qty'))
        if self.detail != 'summary':
            cols.append((_('Rate'), 'n', 'rate'))
        cols += [(_('Value Ex. GST'), 'n', 'ex'), (_('GST %'), 'c', 'gst_pct'), (_('GST'), 'n', 'gst'),
                 (_('Value Incl. GST'), 'n', 'incl'), (_('Comm. %'), 'c', 'comm_pct'), (_('Commission'), 'n', 'comm'),
                 (_('Delivered'), 'q', 'delivered'), (_('Pending Delivery'), 'q', 'pending'),
                 (_('Invoiced'), 'q', 'invoiced'), (_('Delivered, Not Invoiced'), 'q', 'uninvoiced'),
                 (_('Pending Delivery Value'), 'n', 'pending_val'), (_('Uninvoiced Value'), 'n', 'uninv_val')]
        return cols

    def _status(self, figs):
        if all(f['pending'] <= EPS for f in figs):
            return _('Fully delivered') if any(f['uninvoiced'] > EPS for f in figs) else _('Complete')
        return _('Partly delivered') if any(f['delivered'] > EPS for f in figs) else _('Not delivered')

    # ------------------------------------------------------------ data
    def _register_data(self):
        self.ensure_one()
        cols = self._columns()
        keys = [c[2] for c in cols]
        qty_keys = {'qty', 'delivered', 'pending', 'invoiced', 'uninvoiced'}
        sum_keys = {'ex', 'gst', 'incl', 'comm', 'pending_val', 'uninv_val'}

        contracts = []  # (order, [(line, figures)])
        for order in self._orders():
            items = []
            for line in order.order_line.filtered(lambda l: not l.display_type and l.product_id):
                if not self._register_product_ok(line.product_id):
                    continue
                if self.tax_ids and not (line.tax_ids & self.tax_ids):
                    continue
                f = self._line_figures(line)
                if self._line_wanted(f):
                    items.append((line, f))
            if items:
                contracts.append((order, items))

        def head(order):
            return {'contract': order.name, 'date': order._document_date(),
                    'customer': order.partner_id.commercial_partner_id.name}

        def contract_row(order, items):
            figs = [f for _l, f in items]
            uoms = {f['uom'] for f in figs}
            row = head(order)
            for k in sum_keys:
                row[k] = sum(f[k] for f in figs)
            for k in qty_keys:
                row[k] = sum(f[k] for f in figs) if len(uoms) == 1 else None
            row['gst_pct'] = ', '.join(sorted({f['gst_pct'] for f in figs}))
            row['comm_pct'] = figs[0]['comm_pct']
            return row

        def item_rows(order, items, with_contract):
            out = []
            for line, f in items:
                row = dict(f)
                if with_contract:
                    row.update(head(order))
                out.append(row)
                if self.detail == 'deliveries':
                    out.extend(self._delivery_rows(line))
            return out

        def totals(rows):
            main = [r for r in rows if not r.get('_delivery')]
            uoms = {r.get('uom') for r in main}
            tot = {}
            for i, k in enumerate(keys):
                if k in sum_keys:
                    tot[i] = sum(r.get(k) or 0.0 for r in main)
                elif k in qty_keys and len(uoms) == 1 and all(r.get(k) is not None for r in main):
                    tot[i] = sum(r.get(k) or 0.0 for r in main)
            return tot

        def as_list(rows):
            return [[r.get(k) if r.get(k) is not None else ('' if k not in qty_keys | sum_keys else None)
                     for k in keys] for r in rows]

        groups, all_rows = [], []
        if self.layout == 'party':
            by_party = OrderedDict()
            for order, items in sorted(contracts, key=lambda c: (c[0].partner_id.commercial_partner_id.name or '',
                                                                 c[0]._document_date(), c[0].id)):
                by_party.setdefault(order.partner_id.commercial_partner_id, []).append((order, items))
            for party, lst in by_party.items():
                rows = []
                for order, items in lst:
                    rows += [contract_row(order, items)] if self.detail == 'summary' else item_rows(order, items, True)
                all_rows += rows
                sub = _('%s contract(s)', len(lst))
                if party.x_party_type_id:
                    sub = '%s | %s' % (party.x_party_type_id.name, sub)
                groups.append({'title': party.name, 'sub': sub, 'rows': as_list(rows), 'totals': totals(rows)})
        elif self.detail == 'summary':
            rows = [contract_row(order, items) for order, items in contracts]
            all_rows = rows
            if rows:
                groups.append({'title': _('Contracts'), 'sub': _('%s contract(s)', len(rows)),
                               'rows': as_list(rows), 'totals': totals(rows)})
        else:
            for order, items in contracts:
                rows = item_rows(order, items, False)
                all_rows += rows
                agent = order.commission_agent_id
                sub = ' | '.join(p for p in (
                    order.partner_id.commercial_partner_id.name, order._document_date().strftime('%d-%b-%y'),
                    order.client_order_ref and _('Ref: %s', order.client_order_ref),
                    agent and _('Agent: %(a)s %(r)s', a=agent.name, r=items[0][1]['comm_pct']),
                    self._status([f for _l, f in items])) if p)
                groups.append({'title': order.name, 'sub': sub, 'rows': as_list(rows), 'totals': totals(rows)})

        filters = self._register_filter_lines()
        for label, recs in ((_('Contracts'), self.order_ids), (_('Commission Agents'), self.agent_ids),
                            (_('Tax Rates'), self.tax_ids), (_('Salespersons'), self.user_ids)):
            if recs:
                filters.append((label, ', '.join(recs.mapped('display_name'))))
        filters.append((_('Showing'), dict(self._fields['show'].selection)[self.show]))
        return {'title': _('Pending Contracts'), 'filters': filters,
                'columns': [(c[0], c[1]) for c in cols], 'groups': groups,
                'totals': totals(all_rows) if groups else {}}
