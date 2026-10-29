import base64
import io

from odoo import fields, models

from .partner_statement_wizard import ACCOUNTING_FMT, HAIR, HEAD_FILL, INK, RULE, PartnerStatementWizard

try:
    import xlsxwriter
except ImportError:  # always shipped with Odoo, guard only for linters
    xlsxwriter = None

AMOUNT_COLS = ('opening', 'gross', 'net', 'settled', 'others', 'closing')


class PartyOutstandingWizard(models.TransientModel):
    """Entry point: Accounting > Reporting > Party Outstanding Report -
    customers or vendors, a date range, optionally one or more partner
    categories (tags); then Generate Report (PDF) or Generate Excel."""
    _name = 'party.outstanding.wizard'
    _description = 'Party Outstanding Report - print options'

    party_type = fields.Selection([('customer', 'Customers'), ('vendor', 'Vendors')],
                                  string='Parties', required=True, default='customer')
    date_from = fields.Date(string='From', required=True,
                             default=lambda self: fields.Date.context_today(self).replace(month=1, day=1))
    date_to = fields.Date(string='To', required=True, default=fields.Date.context_today)
    category_ids = fields.Many2many('res.partner.category', string='Categories',
                                    help='Only parties tagged with any of these categories. Leave empty for all.')
    hide_zero = fields.Boolean(string='Hide parties with nothing to show', default=True)

    def action_print(self):
        self.ensure_one()
        return self.env.ref('partner_ledger_qty.action_report_party_outstanding').report_action(self)

    def action_print_xlsx(self):
        self.ensure_one()
        data = self.env['report.partner_ledger_qty.party_outstanding_document']._get_po_data(self)
        attachment = self.env['ir.attachment'].create({
            'name': '%s %s to %s.xlsx' % (data['title'], self.date_from, self.date_to),
            'datas': base64.b64encode(self._build_xlsx(data)),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'self',
        }

    def _build_xlsx(self, data):
        buf = io.BytesIO()
        wb = xlsxwriter.Workbook(buf, {'in_memory': True})
        ws = wb.add_worksheet('Party Outstanding')

        base = {'font_name': 'Arial', 'font_size': 9, 'valign': 'vcenter', 'font_color': INK}
        f_co = wb.add_format({**base, 'bold': True, 'font_size': 11})
        f_lbl = wb.add_format({**base, 'font_color': '#6B7280'})
        f_val = wb.add_format({**base, 'bold': True})
        f_date_hdr = wb.add_format({**base, 'num_format': 'd-mmm-yy', 'align': 'left'})
        f_title = wb.add_format({**base, 'bold': True, 'font_size': 14, 'align': 'right'})
        f_sub = wb.add_format({**base, 'font_size': 8, 'font_color': '#6B7280', 'align': 'right'})
        f_head = wb.add_format({**base, 'bold': True, 'align': 'center', 'text_wrap': True,
                                'bg_color': HEAD_FILL, 'top': 1, 'top_color': INK,
                                'bottom': 2, 'bottom_color': INK, 'left': 1, 'right': 1,
                                'left_color': RULE, 'right_color': RULE})
        cell = {**base, 'border': 1, 'border_color': HAIR}
        f_sr = wb.add_format({**cell, 'align': 'center'})
        f_txt = wb.add_format(cell)
        f_date = wb.add_format({**cell, 'num_format': 'd-mmm-yy', 'align': 'center'})
        f_num = wb.add_format({**cell, 'num_format': ACCOUNTING_FMT})
        tot = {**base, 'bold': True, 'bg_color': HEAD_FILL, 'top': 1, 'top_color': INK,
               'bottom': 6, 'bottom_color': INK}
        f_tot = wb.add_format({**tot, 'align': 'center'})
        f_tot_num = wb.add_format({**tot, 'num_format': ACCOUNTING_FMT})

        for col, w in enumerate([6, 38, 12, 12, 14, 14, 14, 14, 14, 14]):
            ws.set_column(col, col, w)

        company = data['company']
        row = 0
        if company.logo:
            scale = PartnerStatementWizard._logo_scale(company.logo)
            ws.set_row(0, 34)
            ws.insert_image(0, 0, 'logo.png', {
                'image_data': io.BytesIO(base64.b64decode(company.logo)),
                'x_scale': scale, 'y_scale': scale, 'object_position': 1,
                'x_offset': 2, 'y_offset': 2,
            })
            row = 1
        ws.write(row, 0, company.name, f_co)
        ws.merge_range(row, 6, row, 9, data['title'].upper(), f_title)
        ws.write(row + 1, 0, 'Period:', f_lbl)
        ws.write_datetime(row + 1, 1, fields.Datetime.to_datetime(data['date_from']), f_date_hdr)
        ws.merge_range(row + 1, 6, row + 1, 9, 'Amounts in %s' % company.currency_id.name, f_sub)
        ws.write(row + 2, 0, 'to', f_lbl)
        ws.write_datetime(row + 2, 1, fields.Datetime.to_datetime(data['date_to']), f_date_hdr)
        if data['categories']:
            ws.write(row + 3, 0, 'Categories:', f_lbl)
            ws.write(row + 3, 1, data['categories'], f_val)
            row += 1

        row += 4
        labels = data['labels']
        headers = ['Sr.', 'Party Name', labels['dlv'], 'Last Inv Date', 'Opening', labels['gross'],
                   labels['net'], labels['settled'], 'Others', 'Closing']
        ws.set_row(row, 26)
        for col, title in enumerate(headers):
            ws.write(row, col, title, f_head)
        ws.freeze_panes(row + 1, 0)
        header_row = row
        row += 1

        for r in data['rows']:
            ws.write_number(row, 0, r['sr'], f_sr)
            ws.write(row, 1, r['partner'] or '', f_txt)
            for col, key in ((2, 'last_dlv'), (3, 'last_inv')):
                if r[key]:
                    ws.write_datetime(row, col, fields.Datetime.to_datetime(r[key]), f_date)
                else:
                    ws.write_blank(row, col, None, f_date)
            for col, key in enumerate(AMOUNT_COLS, start=4):
                ws.write_number(row, col, r[key], f_num)
            row += 1

        ws.merge_range(row, 0, row, 3, 'TOTAL', f_tot)
        for col, key in enumerate(AMOUNT_COLS, start=4):
            ws.write_number(row, col, data['totals'][key], f_tot_num)

        ws.set_landscape()
        ws.set_paper(9)
        ws.set_margins(left=0.25, right=0.25, top=0.5, bottom=0.5)
        ws.fit_to_pages(1, 0)
        ws.repeat_rows(header_row)
        ws.hide_gridlines(2)
        wb.close()
        return buf.getvalue()
