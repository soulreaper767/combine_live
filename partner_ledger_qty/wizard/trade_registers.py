from collections import OrderedDict

from odoo import _, fields, models

SALE_TYPES = ('out_invoice', 'out_refund')
PURCHASE_TYPES = ('in_invoice', 'in_refund')


class TradeRegisterWizard(models.TransientModel):
    """Sales Register / Purchase Register: every invoice (bill) line in the
    period, grouped party-wise or item-wise, with rate, discount, gross,
    net, tax and value incl. tax - the Partner Ledger seen from the sales
    (purchase) side. Credit notes / debit notes come in negative."""
    _name = 'combine.trade.register.wizard'
    _inherit = 'combine.register.mixin'
    _description = 'Sales / Purchase Register'
    _register_report_xmlid = 'partner_ledger_qty.action_report_trade_register'

    kind = fields.Selection([('sale', 'Sales'), ('purchase', 'Purchases')], required=True, default='sale')
    group_by = fields.Selection([('party', 'Party-wise'), ('item', 'Item-wise')], required=True, default='party')
    detail = fields.Selection([('detail', 'Every line'), ('summary', 'Summary (one line per party / item)')],
                              required=True, default='detail')
    tax_ids = fields.Many2many('account.tax', 'combine_treg_tax_rel', 'wizard_id', 'tax_id', string='Tax Rates',
                               context={'active_test': False},
                               help='Only lines carrying one of these taxes. Leave empty for all (lines without tax included).')

    def _register_lines(self):
        types = SALE_TYPES if self.kind == 'sale' else PURCHASE_TYPES
        lines = self.env['account.move.line'].search([
            ('company_id', '=', self.env.company.id),
            ('parent_state', '=', 'posted'),
            ('move_id.move_type', 'in', types),
            ('display_type', '=', 'product'),
            ('move_id.invoice_date', '>=', self.date_from),
            ('move_id.invoice_date', '<=', self.date_to),
        ], order='date, move_id, sequence, id')
        helper = self.env['partner_ledger_qty.voucher.mixin']
        out = []
        for line in lines:
            move = line.move_id
            if not self._register_partner_ok(move.partner_id) or not self._register_product_ok(line.product_id):
                continue
            if self.tax_ids and not (line.tax_ids & self.tax_ids):
                continue
            sign = -1 if move.move_type in ('out_refund', 'in_refund') else 1
            disc = helper._discount_values(line, line.quantity, move.currency_id, move.partner_id)
            gross = disc['_gross']
            out.append({
                'date': move.invoice_date, 'doc': move.name, 'party': move.partner_id.commercial_partner_id,
                'product': line.product_id, 'label': line.product_id.display_name or line.name or '',
                'qty': sign * line.quantity, 'uom': line.product_uom_id.name or '',
                'rate': gross / line.quantity if line.quantity else 0.0, 'disc_pct': line.discount,
                'gross': sign * gross, 'discount': sign * disc['_disc'], 'net': sign * line.price_subtotal,
                'tax': sign * (line.price_total - line.price_subtotal), 'incl': sign * line.price_total,
            })
        return out

    def _register_data(self):
        self.ensure_one()
        lines = self._register_lines()
        by_party = self.group_by == 'party'
        title = (_('Sales Register') if self.kind == 'sale' else _('Purchase Register')) + ' - ' + \
            (_('Party-wise') if by_party else _('Item-wise'))
        money = ('gross', 'discount', 'net', 'tax', 'incl')
        groups = OrderedDict()
        for ln in lines:
            key = ln['party'] if by_party else ln['product']
            groups.setdefault(key, []).append(ln)
        keys = sorted(groups, key=lambda k: (k.display_name or '').lower())

        if self.detail == 'summary':
            columns = [(_('Party') if by_party else _('Item'), 't'), (_('Documents'), 'c'), (_('Quantity'), 'q'),
                       (_('UoM'), 'c'), (_('Gross Value'), 'n'), (_('Discount'), 'n'), (_('Net Value'), 'n'),
                       (_('Sales Tax'), 'n'), (_('Value Incl. Tax'), 'n')]
            rows = []
            for k in keys:
                g = groups[k]
                uoms = {ln['uom'] for ln in g}
                rows.append([k.display_name, len({ln['doc'] for ln in g}),
                             sum(ln['qty'] for ln in g) if len(uoms) == 1 else None, uoms.pop() if len(uoms) == 1 else _('mixed'),
                             *[sum(ln[m] for ln in g) for m in money]])
            data_groups = [{'title': _('Summary'), 'rows': rows, 'totals': {}}] if rows else []
            totals = {i: sum(r[i] for r in rows) for i in (4, 5, 6, 7, 8)} if rows else {}
        else:
            columns = [(_('Date'), 'd'), (_('Document'), 't'), (_('Item') if by_party else _('Party'), 't'),
                       (_('Quantity'), 'q'), (_('UoM'), 'c'), (_('Rate'), 'n'), (_('Disc. %'), 'c'),
                       (_('Gross Value'), 'n'), (_('Discount'), 'n'), (_('Net Value'), 'n'), (_('Sales Tax'), 'n'),
                       (_('Value Incl. Tax'), 'n')]
            data_groups = []
            for k in keys:
                g = groups[k]
                rows = [[ln['date'], ln['doc'], ln['label'] if by_party else ln['party'].display_name, ln['qty'], ln['uom'],
                         ln['rate'], f"{ln['disc_pct']:g}%" if ln['disc_pct'] else '-',
                         *[ln[m] for m in money]] for ln in g]
                uoms = {ln['uom'] for ln in g}
                sub = {7 + i: sum(ln[m] for ln in g) for i, m in enumerate(money)}
                if len(uoms) == 1:
                    sub[3] = sum(ln['qty'] for ln in g)
                extra = k.x_party_type_id.name if by_party and 'x_party_type_id' in k._fields and k.x_party_type_id else ''
                data_groups.append({'title': k.display_name, 'sub': extra, 'rows': rows, 'totals': sub})
            totals = {7 + i: sum(ln[m] for ln in lines) for i, m in enumerate(money)} if lines else {}
        filters = self._register_filter_lines()
        if self.tax_ids:
            filters.append((_('Tax Rates'), ', '.join(self.tax_ids.mapped('name'))))
        return {'title': title, 'filters': filters, 'columns': columns,
                'groups': data_groups, 'totals': totals}


class OrderStatusWizard(models.TransientModel):
    """Contract / Sales Order Status and Purchase Order Status: one block per
    document - each item ordered, delivered (received), balance, invoiced
    (billed), still to invoice, and the values - then the next document."""
    _name = 'combine.order.status.wizard'
    _inherit = 'combine.register.mixin'
    _description = 'Contract / Purchase Order Status'
    _register_report_xmlid = 'partner_ledger_qty.action_report_order_status'

    kind = fields.Selection([('sale', 'Contracts / Sales Orders'), ('purchase', 'Purchase Orders')], required=True, default='sale')
    open_only = fields.Boolean(string='Only documents with a balance', default=True,
                               help='Hide documents that are fully delivered (received).')

    @staticmethod
    def _order_line_balance(line, ordered, moved):
        """Balance = what is still due on open deliveries (receipts); what is
        neither moved nor due was cancelled (e.g. rejected goods cancelled
        from the PO, a cancelled backorder)."""
        moves = line.move_ids.filtered(lambda m: not m.origin_returned_move_id)
        if not moves:
            return max(ordered - moved, 0.0), 0.0
        due = sum(m.product_uom._compute_quantity(m.product_uom_qty, line.product_uom_id)
                  for m in moves if m.state not in ('done', 'cancel'))
        due = min(due, max(ordered - moved, 0.0))
        return due, max(ordered - moved - due, 0.0)

    def _register_data(self):
        self.ensure_one()
        sale = self.kind == 'sale'
        Order = self.env['sale.order' if sale else 'purchase.order']
        states = ('sale',) if sale else ('purchase', 'done')
        orders = Order.search([('company_id', '=', self.env.company.id), ('state', 'in', states),
                               '|', '&', ('x_document_date', '>=', self.date_from), ('x_document_date', '<=', self.date_to),
                               '&', '&', ('x_document_date', '=', False),
                               ('date_order', '>=', fields.Datetime.to_datetime(self.date_from)),
                               ('date_order', '<', fields.Datetime.add(fields.Datetime.to_datetime(self.date_to), days=1))])
        orders = orders.sorted(lambda o: (o._document_date(), o.id))
        moved_lbl = _('Delivered') if sale else _('Received')
        inv_lbl = _('Invoiced') if sale else _('Billed')
        columns = [(_('Item'), 't'), (_('UoM'), 'c'), (_('Ordered'), 'q'), (moved_lbl, 'q'), (_('Balance'), 'q'),
                   (_('Cancelled'), 'q'), (inv_lbl, 'q'), (_('To Invoice') if sale else _('To Bill'), 'q'), (_('Rate (Net)'), 'n'),
                   (_('Order Value'), 'n'), (moved_lbl + _(' Value'), 'n'), (_('Balance Value'), 'n')]
        groups, grand = [], {9: 0.0, 10: 0.0, 11: 0.0}
        for order in orders:
            if not self._register_partner_ok(order.partner_id):
                continue
            rows = []
            for line in order.order_line.filtered(lambda l: not l.display_type and l.product_id):
                if not self._register_product_ok(line.product_id):
                    continue
                ordered = line.product_uom_qty if sale else line.product_qty
                moved = line.qty_delivered if sale else line.qty_received
                invoiced = line.qty_invoiced
                rate = line.price_subtotal / ordered if ordered else 0.0
                balance, cancelled = self._order_line_balance(line, ordered, moved)
                rows.append([line.product_id.display_name, line.product_uom_id.name, ordered, moved, balance, cancelled,
                             invoiced, moved - invoiced if moved > invoiced else 0.0, rate,
                             line.price_subtotal, moved * rate, balance * rate])
            if not rows:
                continue
            if self.open_only and all(abs(r[4]) < 0.0001 for r in rows):
                continue
            totals = {i: sum(r[i] for r in rows) for i in (9, 10, 11)}
            uoms = {r[1] for r in rows}
            if len(uoms) == 1:
                totals.update({i: sum(r[i] for r in rows) for i in (2, 3, 4, 5, 6, 7)})
            for i in grand:
                grand[i] += totals[i]
            status = (_('Closed - part cancelled') if any(r[5] > 0.0001 for r in rows) else _('Complete')) if all(abs(r[4]) < 0.0001 for r in rows) else (
                _('Partly %s', moved_lbl.lower()) if any(r[3] for r in rows) else _('Pending'))
            ref = order.client_order_ref if sale else order.partner_ref
            sub = ' | '.join(p for p in (order.partner_id.commercial_partner_id.name,
                                         order._document_date().strftime('%d-%b-%y'),
                                         ref and _('Ref: %s', ref), status) if p)
            groups.append({'title': order.name, 'sub': sub, 'rows': rows, 'totals': totals})
        filters = self._register_filter_lines()
        if self.open_only:
            filters.append((_('Showing'), _('only documents with a balance')))
        title = _('Contract / Sales Order Status') if sale else _('Purchase Order Status')
        return {'title': title, 'filters': filters, 'columns': columns, 'groups': groups,
                'totals': grand if groups else {}}
