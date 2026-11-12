"""Total Sales Report (Sales > Reporting): posted customer invoices (and
credit notes, as negatives) line by line or summarised, grouped by party,
item and/or tax rate (any combination, in that order).

Per line: quantity, unit, rate as invoiced, discount, gross value (before
discount), discount amount, value excluding tax, tax rate and amount, value
including tax, net rate excluding tax, commission rate and amount.
Read-only; rendered by Custom Reports' register engine (house-style PDF/Excel).
"""
from collections import OrderedDict

from odoo import _, fields, models
from odoo.exceptions import UserError

NUM_KEYS = ('qty', 'gross', 'discount', 'ex', 'tax', 'incl', 'comm')


class TotalSalesWizard(models.TransientModel):
    _name = 'combine.total.sales.wizard'
    _inherit = 'combine.register.mixin'
    _description = 'Total Sales Report'
    _register_report_xmlid = 'combine_commission.action_report_total_sales'

    by_party = fields.Boolean(string='By Party', default=True)
    by_item = fields.Boolean(string='By Item')
    by_tax = fields.Boolean(string='By Tax Rate')
    detail = fields.Selection([('detail', 'Every invoice line'), ('summary', 'Summary (one line per group)')],
                              string='Detail', required=True, default='summary')
    include_refunds = fields.Boolean(string='Include credit notes', default=True,
                                     help='Credit notes are shown as negative sales.')
    tax_ids = fields.Many2many('account.tax', 'combine_tsales_tax_rel', 'wizard_id', 'tax_id', string='Tax Rates',
                               domain=[('type_tax_use', '=', 'sale')], help='Leave empty for all tax rates.')
    agent_ids = fields.Many2many('combine001.commission.agent', 'combine_tsales_agent_rel', 'wizard_id', 'agent_id',
                                 string='Commission Agents', help='Leave empty for all.')
    user_ids = fields.Many2many('res.users', 'combine_tsales_user_rel', 'wizard_id', 'user_id', string='Salespersons',
                                help='Leave empty for all.')

    # ------------------------------------------------------------ lines
    def _lines(self):
        types = ('out_invoice', 'out_refund') if self.include_refunds else ('out_invoice',)
        domain = [('move_id.move_type', 'in', types), ('move_id.state', '=', 'posted'), ('display_type', '=', 'product'),
                  ('move_id.company_id', '=', self.env.company.id),
                  ('move_id.invoice_date', '>=', self.date_from), ('move_id.invoice_date', '<=', self.date_to)]
        if self.tax_ids:
            domain.append(('tax_ids', 'in', self.tax_ids.ids))
        if self.user_ids:
            domain.append(('move_id.invoice_user_id', 'in', self.user_ids.ids))
        lines = self.env['account.move.line'].search(domain).sorted(
            lambda l: (l.move_id.invoice_date, l.move_id.name or '', l.id))
        CL = self.env['combine001.commission.line'].sudo()
        comm = {c.invoice_line_id.id: c for c in CL.search([('invoice_line_id', 'in', lines.ids)])}
        out = []
        for line in lines:
            move = line.move_id
            partner = move.partner_id.commercial_partner_id
            if not self._register_partner_ok(partner):
                continue
            if line.product_id and not self._register_product_ok(line.product_id):
                continue
            c = comm.get(line.id)
            if self.agent_ids and not (c and c.agent_id in self.agent_ids):
                continue
            sign = -1.0 if move.move_type == 'out_refund' else 1.0
            qty = line.quantity * sign
            gross = line.price_unit * line.quantity * sign
            discount = gross * (line.discount or 0.0) / 100.0
            ex = line.price_subtotal * sign
            incl = line.price_total * sign
            tax_pct = ', '.join('{:g}%'.format(t.amount) for t in line.tax_ids) or _('No tax')
            out.append({
                'date': move.invoice_date, 'invoice': move.name, 'party': partner.name or '',
                'party_key': partner.id, 'item': line.product_id.display_name or line.name or '',
                'item_key': line.product_id.id or 0, 'uom': line.product_uom_id.name or '',
                'qty': qty, 'rate': line.price_unit, 'disc_pct': '{:g}%'.format(line.discount) if line.discount else '',
                'gross': gross, 'discount': discount, 'ex': ex, 'tax_pct': tax_pct, 'tax': incl - ex, 'incl': incl,
                'net_rate': (ex / qty) if qty else 0.0,
                'comm_pct': '{:g}%'.format(c.rate) if c else '', 'comm': (c.commission_amount if c else 0.0),
                'agent': c.agent_id.name if c else '',
            })
        return out

    # ------------------------------------------------------------ layout
    def _dims(self):
        dims = []
        if self.by_party:
            dims.append(('party', _('Party')))
        if self.by_item:
            dims.append(('item', _('Item')))
        if self.by_tax:
            dims.append(('tax_pct', _('Tax Rate')))
        return dims

    def _columns(self, dims):
        dim_keys = [d[0] for d in dims]
        if self.detail == 'detail':
            cols = [(_('Date'), 'd', 'date'), (_('Invoice'), 't', 'invoice')]
            if 'party' not in dim_keys:
                cols.append((_('Party'), 't', 'party'))
            if 'item' not in dim_keys:
                cols.append((_('Item'), 't', 'item'))
            cols += [(_('UoM'), 'c', 'uom'), (_('Qty'), 'q', 'qty'), (_('Rate'), 'n', 'rate'), (_('Disc.'), 'c', 'disc_pct')]
        else:
            rest = dims[1:] if len(dims) > 1 else dims
            cols = [(label, 't', key) for key, label in rest]
            cols += [(_('Invoices'), 'c', 'count'), (_('UoM'), 'c', 'uom'), (_('Qty'), 'q', 'qty'),
                     (_('Avg Rate'), 'n', 'rate')]
        cols += [(_('Gross Value (Rate x Qty)'), 'n', 'gross'), (_('Discount'), 'n', 'discount'),
                 (_('Net Rate (Ex. Tax)'), 'n', 'net_rate'), (_('Value Ex. Tax'), 'n', 'ex')]
        if 'tax_pct' not in dim_keys or self.detail == 'detail':
            cols.append((_('Tax %'), 'c', 'tax_pct'))
        cols += [(_('Tax'), 'n', 'tax'), (_('Value Incl. Tax'), 'n', 'incl'),
                 (_('Comm. %'), 'c', 'comm_pct'), (_('Commission'), 'n', 'comm')]
        return cols

    @staticmethod
    def _summarise(rows):
        out = {k: sum(r[k] for r in rows) for k in NUM_KEYS}
        uoms = {r['uom'] for r in rows}
        out['uom'] = ', '.join(sorted(u for u in uoms if u))
        if len(uoms) != 1:
            out['qty'] = None
        qty = out['qty']
        gross_qty = sum(r['qty'] for r in rows)
        out['rate'] = (sum(r['rate'] * r['qty'] for r in rows) / gross_qty) if gross_qty and qty is not None else None
        out['net_rate'] = (out['ex'] / qty) if qty else None
        out['count'] = str(len({r['invoice'] for r in rows}))
        out['tax_pct'] = ', '.join(sorted({r['tax_pct'] for r in rows}))
        pcts = sorted({r['comm_pct'] for r in rows if r['comm_pct']})
        out['comm_pct'] = ', '.join(pcts)
        return out

    def _register_data(self):
        self.ensure_one()
        dims = self._dims()
        if not dims and self.detail == 'summary':
            raise UserError(_('Tick at least one of By Party, By Item or By Tax Rate for a summary.'))
        cols = self._columns(dims)
        keys = [c[2] for c in cols]
        lines = self._lines()

        def as_row(r):
            return [r.get(k) if r.get(k) is not None else ('' if k not in NUM_KEYS + ('rate', 'net_rate') else None)
                    for k in keys]

        def totals(rows):
            s = self._summarise(rows) if rows else {}
            tot = {}
            for i, k in enumerate(keys):
                if k in NUM_KEYS and s.get(k) is not None:
                    tot[i] = s[k]
            return tot

        groups = []
        if self.detail == 'detail':
            buckets = OrderedDict()
            ordered = sorted(lines, key=lambda r: tuple(str(r[d]) for d, _l in dims) + (r['date'], r['invoice'] or '')) \
                if dims else lines
            for r in ordered:
                buckets.setdefault(tuple(r[d] for d, _l in dims), []).append(r)
            for key, rows in buckets.items():
                title = ' > '.join(str(k) for k in key) if key else _('All sales')
                groups.append({'title': title, 'sub': _('%s line(s)', len(rows)),
                               'rows': [as_row(r) for r in rows], 'totals': totals(rows)})
        else:
            first = dims[0][0]
            rest = [d[0] for d in dims[1:]]
            if not rest:
                summary = [dict(self._summarise(rows), **{first: name})
                           for name, rows in self._group(lines, first).items()]
                if summary:
                    groups.append({'title': dims[0][1], 'sub': _('%s line(s)', len(summary)),
                                   'rows': [as_row(r) for r in summary], 'totals': totals(lines)})
            else:
                for name, rows in self._group(lines, first).items():
                    sub_rows = []
                    for key, part in self._group(rows, rest).items():
                        vals = dict(self._summarise(part))
                        vals.update(dict(zip(rest, key)))
                        sub_rows.append(vals)
                    groups.append({'title': name, 'sub': _('%s line(s)', len(sub_rows)),
                                   'rows': [as_row(r) for r in sub_rows], 'totals': totals(rows)})
        filters = self._register_filter_lines()
        for label, recs in ((_('Tax Rates'), self.tax_ids), (_('Commission Agents'), self.agent_ids),
                            (_('Salespersons'), self.user_ids)):
            if recs:
                filters.append((label, ', '.join(recs.mapped('display_name'))))
        filters.append((_('Grouped by'), ' > '.join(l for _k, l in dims) or _('none')))
        if not self.include_refunds:
            filters.append((_('Credit notes'), _('excluded')))
        return {'title': _('Total Sales Report'), 'filters': filters, 'columns': [(c[0], c[1]) for c in cols],
                'groups': groups, 'totals': totals(lines) if groups else {}}

    @staticmethod
    def _group(rows, keys):
        out = OrderedDict()
        if isinstance(keys, str):
            for r in sorted(rows, key=lambda r: str(r[keys])):
                out.setdefault(r[keys], []).append(r)
            return out
        for r in sorted(rows, key=lambda r: tuple(str(r[k]) for k in keys)):
            out.setdefault(tuple(r[k] for k in keys), []).append(r)
        return out
