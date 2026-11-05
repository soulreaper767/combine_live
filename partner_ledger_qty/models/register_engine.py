"""Shared engine for the document registers (Sales / Purchase Register,
Contract & PO Status, the stores registers ...).

A register wizard inherits `combine.register.mixin` and implements
`_register_data()`, returning:

    {'title': str,
     'filters': [(label, text), ...],                 # printed under the header
     'columns': [(label, kind), ...],                 # kind: 't' text, 'c' centred text,
                                                      #       'd' date, 'q' quantity, 'n' amount
     'groups': [{'title': str, 'sub': str,            # one block per document / party / item
                 'rows': [[value, ...], ...],
                 'totals': {col_index: value}}],
     'totals': {col_index: value}}                    # grand total (optional)

The one PDF template (report/register_report.xml) and the Excel builder
below render any of them in the house style."""
import base64
import io

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import format_date


try:
    import xlsxwriter
except ImportError:  # always shipped with Odoo
    xlsxwriter = None

QTY_FMT = '_(* #,##0.00_);_(* \\(#,##0.00\\);_(* "-"??_);_(@_)'
AMT_FMT = '_(* #,##0.00_);_(* \\(#,##0.00\\);_(* "-"??_);_(@_)'


class RegisterMixin(models.AbstractModel):
    _name = 'combine.register.mixin'
    _description = 'Document register - common options'

    date_from = fields.Date(string='From', required=True,
                            default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date(string='To', required=True, default=fields.Date.context_today)
    partner_ids = fields.Many2many('res.partner', string='Parties', help='Leave empty for all parties.')
    party_type_ids = fields.Many2many('combine.party.type', string='Party Types', help='Leave empty for all party types.')
    product_ids = fields.Many2many('product.product', string='Items', help='Leave empty for all items.')
    categ_ids = fields.Many2many('product.category', string='Item Categories',
                                 help='Items in these categories (and their sub-categories). Leave empty for all.')

    _register_report_xmlid = None

    # ---- to implement --------------------------------------------------
    def _register_data(self):
        raise NotImplementedError

    # ---- shared filters ------------------------------------------------
    def _register_partner_ok(self, partner):
        partner = partner.commercial_partner_id
        if self.partner_ids and partner not in self.partner_ids.commercial_partner_id:
            return False
        if self.party_type_ids and partner.x_party_type_id not in self.party_type_ids:
            return False
        return True

    def _register_product_ok(self, product):
        if self.product_ids and product not in self.product_ids:
            return False
        if self.categ_ids:
            cat = product.categ_id
            wanted = set(self.categ_ids.ids)
            while cat:
                if cat.id in wanted:
                    return True
                cat = cat.parent_id
            return False
        return True

    def _register_filter_lines(self):
        out = []
        for label, recs in ((_('Parties'), self.partner_ids), (_('Party Types'), self.party_type_ids),
                            (_('Items'), self.product_ids), (_('Item Categories'), self.categ_ids)):
            if recs:
                out.append((label, ', '.join(recs.mapped('display_name'))))
        return out

    # ---- formatting ----------------------------------------------------
    @api.model
    def _register_cell(self, value, kind):
        if value is None or value is False or value == '':
            return ''
        if kind in ('n', 'q'):
            if isinstance(value, str):
                return value
            return '-' if abs(value) < 0.005 else f'{value:,.2f}'
        if kind == 'd':
            return format_date(self.env, value, date_format='dd-MMM-yy')
        return value

    @api.model
    def _register_class(self, kind):
        return {'n': 'n', 'q': 'n', 'c': 'c', 'd': 'c nw'}.get(kind, '')

    # ---- actions -------------------------------------------------------
    def _register_check(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise UserError(_('"From" must be on or before "To".'))

    def action_print(self):
        self.ensure_one()
        self._register_check()
        return self.env.ref(self._register_report_xmlid).report_action(self)

    def action_print_xlsx(self):
        self.ensure_one()
        self._register_check()
        data = self._register_data()
        attachment = self.env['ir.attachment'].create({
            'name': '%s %s to %s.xlsx' % (data['title'], self.date_from, self.date_to),
            'datas': base64.b64encode(self._register_xlsx(data)),
            'res_model': self._name, 'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {'type': 'ir.actions.act_url', 'url': '/web/content/%s?download=true' % attachment.id, 'target': 'self'}

    def _register_xlsx(self, data):
        # imported here: the wizard package imports this module's mixin
        from ..wizard.partner_statement_wizard import ACCOUNTING_FMT, HAIR, HEAD_FILL, INK, RULE, PartnerStatementWizard
        buf = io.BytesIO()
        wb = xlsxwriter.Workbook(buf, {'in_memory': True})
        ws = wb.add_worksheet(data['title'][:31])
        cols = data['columns']
        last = len(cols) - 1
        base = {'font_name': 'Arial', 'font_size': 9, 'valign': 'vcenter', 'font_color': INK}
        f_co = wb.add_format({**base, 'bold': True, 'font_size': 11})
        f_title = wb.add_format({**base, 'bold': True, 'font_size': 14, 'align': 'right'})
        f_sub = wb.add_format({**base, 'font_size': 8, 'font_color': '#6B7280', 'align': 'right'})
        f_lbl = wb.add_format({**base, 'font_color': '#6B7280'})
        f_val = wb.add_format({**base, 'bold': True})
        f_head = wb.add_format({**base, 'bold': True, 'align': 'center', 'text_wrap': True, 'bg_color': HEAD_FILL,
                                'top': 1, 'top_color': INK, 'bottom': 2, 'bottom_color': INK,
                                'left': 1, 'right': 1, 'left_color': RULE, 'right_color': RULE})
        cell = {**base, 'border': 1, 'border_color': HAIR}
        fmt = {
            't': wb.add_format(cell), 'c': wb.add_format({**cell, 'align': 'center'}),
            'd': wb.add_format({**cell, 'num_format': 'dd-mmm-yy', 'align': 'center'}),
            'q': wb.add_format({**cell, 'num_format': QTY_FMT}), 'n': wb.add_format({**cell, 'num_format': AMT_FMT}),
        }
        grp = {**base, 'bold': True, 'bg_color': '#FAFAFA', 'top': 1, 'top_color': RULE}
        f_grp = wb.add_format(grp)
        sub = {**base, 'bold': True, 'top': 1, 'top_color': RULE, 'bottom': 1, 'bottom_color': RULE}
        f_sub_t = wb.add_format(sub)
        f_sub_n = wb.add_format({**sub, 'num_format': AMT_FMT})
        tot = {**base, 'bold': True, 'bg_color': HEAD_FILL, 'top': 1, 'top_color': INK, 'bottom': 6, 'bottom_color': INK}
        f_tot_t = wb.add_format(tot)
        f_tot_n = wb.add_format({**tot, 'num_format': AMT_FMT})

        widths = {'t': 30, 'c': 12, 'd': 11, 'q': 13, 'n': 15}
        for i, (_label, kind) in enumerate(cols):
            ws.set_column(i, i, widths.get(kind, 14))
        company = self.env.company
        row = 0
        if company.logo:
            scale = PartnerStatementWizard._logo_scale(company.logo)
            ws.set_row(0, 34)
            ws.insert_image(0, 0, 'logo.png', {'image_data': io.BytesIO(base64.b64decode(company.logo)),
                                               'x_scale': scale, 'y_scale': scale, 'object_position': 1})
            row = 1
        ws.write(row, 0, company.name, f_co)
        right = max(last - 3, 1)
        ws.merge_range(row, right, row, last, data['title'].upper(), f_title)
        ws.write(row + 1, 0, _('Period:'), f_lbl)
        ws.write(row + 1, 1, '%s to %s' % (format_date(self.env, self.date_from, date_format='dd-MMM-yy'), format_date(self.env, self.date_to, date_format='dd-MMM-yy')), f_val)
        ws.merge_range(row + 1, right, row + 1, last, _('Amounts in %s') % company.currency_id.name, f_sub)
        row += 2
        for label, text in data.get('filters', []):
            ws.write(row, 0, label + ':', f_lbl)
            ws.write(row, 1, text, f_val)
            row += 1
        row += 1
        ws.set_row(row, 28)
        for i, (label, _kind) in enumerate(cols):
            ws.write(row, i, label, f_head)
        ws.freeze_panes(row + 1, 0)
        header_row = row
        row += 1

        def put(r, c, value, kind, style=None):
            if value is None or value is False or value == '':
                ws.write_blank(r, c, None, style or fmt[kind])
            elif kind == 'd':
                ws.write_datetime(r, c, fields.Datetime.to_datetime(value), style or fmt['d'])
            elif kind in ('n', 'q') and not isinstance(value, str):
                ws.write_number(r, c, value, style or fmt[kind])
            else:
                ws.write(r, c, value, style or fmt[kind if kind in fmt else 't'])

        for g in data['groups']:
            ws.merge_range(row, 0, row, last, ' - '.join(p for p in (g['title'], g.get('sub')) if p), f_grp)
            row += 1
            for r in g['rows']:
                for c, value in enumerate(r):
                    put(row, c, value, cols[c][1])
                row += 1
            if g.get('totals'):
                ws.write(row, 0, _('Subtotal'), f_sub_t)
                for c in range(1, len(cols)):
                    v = g['totals'].get(c)
                    if v is None:
                        ws.write_blank(row, c, None, f_sub_t)
                    else:
                        put(row, c, v, cols[c][1], f_sub_n)
                row += 1
        if data.get('totals'):
            ws.write(row, 0, _('GRAND TOTAL'), f_tot_t)
            for c in range(1, len(cols)):
                v = data['totals'].get(c)
                if v is None:
                    ws.write_blank(row, c, None, f_tot_t)
                else:
                    put(row, c, v, cols[c][1], f_tot_n)
        ws.set_landscape()
        ws.set_paper(9)
        ws.set_margins(left=0.25, right=0.25, top=0.5, bottom=0.5)
        ws.fit_to_pages(1, 0)
        ws.repeat_rows(header_row)
        ws.hide_gridlines(2)
        wb.close()
        return buf.getvalue()
