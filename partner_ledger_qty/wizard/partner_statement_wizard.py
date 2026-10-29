import base64
import io

from odoo import fields, models

try:
    import xlsxwriter
except ImportError:  # always shipped with Odoo, guard only for linters
    xlsxwriter = None

# Same number format as the user's Excel reference (partner_ledger.xlsx):
# zero decimals, "-" for zero, parentheses for negatives.
ACCOUNTING_FMT = '_(* #,##0_);_(* \\(#,##0\\);_(* "-"??_);_(@_)'
HEAD_FILL = '#F3F4F6'
INK = '#1F2937'
HAIR = '#E5E7EB'
RULE = '#CBD5E1'

COLUMNS = [
    # (title, width)
    ('Date', 10.8), ('V. No.', 20.8), ('Remarks', 28), ('Item', 16), ('Inv Age', 7),
    ('Gross Rate', 9.5), ('Qty', 8), ('Disc.', 7), ('Net Rate', 9.5), ('Ex. Amt', 11),
    ('GST Rate', 8), ('GST Amt', 10), ('Incl. Amt', 11), ('', 0.6),
    ('Debit', 12), ('Credit', 12), ('Balance', 13),
]


class PartnerStatementWizard(models.TransientModel):
    """Entry point: Accounting > Reporting > Partner Ledger Print - pick a
    partner and a date range, then Generate Report (PDF) or Generate
    Excel (.xlsx with the same columns, totals and number formats)."""
    _name = 'partner.ledger.statement.wizard'
    _description = 'Partner Statement - print options'

    partner_id = fields.Many2one('res.partner', string='Partner', required=True)
    date_from = fields.Date(string='From', required=True,
                             default=lambda self: fields.Date.context_today(self).replace(month=1, day=1))
    date_to = fields.Date(string='To', required=True, default=fields.Date.context_today)

    def action_print(self):
        self.ensure_one()
        return self.env.ref('partner_ledger_qty.action_report_partner_statement').report_action(self)

    def action_print_xlsx(self):
        self.ensure_one()
        report = self.env['report.partner_ledger_qty.partner_statement_document']
        data = report._get_statement_data(self)
        content = self._build_xlsx(data)
        filename = 'Partner Ledger - %s.xlsx' % self.partner_id.name
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'datas': base64.b64encode(content),
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
        ws = wb.add_worksheet('Partner Ledger')

        base = {'font_name': 'Arial', 'font_size': 9, 'valign': 'vcenter', 'font_color': INK}
        f_co = wb.add_format({**base, 'bold': True, 'font_size': 11})
        f_lbl = wb.add_format({**base, 'font_color': '#6B7280'})
        f_val = wb.add_format({**base, 'bold': True})
        f_txt = wb.add_format(base)
        f_date_hdr = wb.add_format({**base, 'num_format': 'd-mmm-yy', 'align': 'left'})
        f_title = wb.add_format({**base, 'bold': True, 'font_size': 14, 'align': 'right'})
        f_sub = wb.add_format({**base, 'font_size': 8, 'font_color': '#6B7280', 'align': 'right'})

        cell = {**base, 'border': 1, 'border_color': HAIR}
        f_head = wb.add_format({**base, 'bold': True, 'align': 'center', 'text_wrap': True,
                                'bg_color': HEAD_FILL, 'top': 1, 'top_color': INK,
                                'bottom': 2, 'bottom_color': INK, 'left': 1, 'right': 1,
                                'left_color': RULE, 'right_color': RULE})
        f_date = wb.add_format({**cell, 'num_format': 'd-mmm-yy', 'align': 'center'})
        f_text = wb.add_format({**cell, 'text_wrap': True, 'valign': 'top'})
        f_center = wb.add_format({**cell, 'align': 'center'})
        f_num = wb.add_format({**cell, 'num_format': ACCOUNTING_FMT})
        f_pct = wb.add_format({**cell, 'num_format': '0%', 'align': 'center'})
        f_open = wb.add_format({**cell, 'italic': True, 'font_color': '#4B5563'})
        f_open_date = wb.add_format({**cell, 'italic': True, 'font_color': '#4B5563',
                                     'num_format': 'd-mmm-yy', 'align': 'center'})
        f_open_num = wb.add_format({**cell, 'italic': True, 'num_format': ACCOUNTING_FMT})
        tot = {**base, 'bold': True, 'bg_color': HEAD_FILL, 'top': 1, 'top_color': INK,
               'bottom': 6, 'bottom_color': INK}
        f_tot = wb.add_format({**tot, 'align': 'center'})
        f_tot_num = wb.add_format({**tot, 'num_format': ACCOUNTING_FMT})
        f_tot_blank = wb.add_format(tot)

        for col, (_title, width) in enumerate(COLUMNS):
            ws.set_column(col, col, width)
        gap = 13  # the narrow divider column before Debit

        # header block
        company = data['company']
        row = 0
        if company.logo:
            scale = self._logo_scale(company.logo)
            ws.set_row(0, 34)
            ws.insert_image(0, 0, 'logo.png', {
                'image_data': io.BytesIO(base64.b64decode(company.logo)),
                'x_scale': scale, 'y_scale': scale, 'object_position': 1,
                'x_offset': 2, 'y_offset': 2,
            })
            row = 1
        ws.write(row, 0, company.name, f_co)
        ws.merge_range(row, 13, row, 16, 'PARTNER LEDGER', f_title)
        ws.write(row + 1, 0, 'Party Name:', f_lbl)
        ws.write(row + 1, 1, data['partner'].name, f_val)
        ws.merge_range(row + 1, 13, row + 1, 16, 'Amounts in %s' % data['currency'].name, f_sub)
        ws.write(row + 2, 0, 'Period:', f_lbl)
        ws.write_datetime(row + 2, 1, fields.Datetime.to_datetime(data['date_from']), f_date_hdr)
        ws.write(row + 2, 2, 'to', f_txt)
        ws.write_datetime(row + 2, 3, fields.Datetime.to_datetime(data['date_to']), f_date_hdr)

        # table header
        row += 4
        ws.set_row(row, 26)
        for col, (title, _w) in enumerate(COLUMNS):
            if col == gap:
                continue
            ws.write(row, col, title, f_head)
        ws.freeze_panes(row + 1, 0)
        first_table_row = row
        row += 1

        # opening balance
        ws.write_datetime(row, 0, fields.Datetime.to_datetime(data['date_from']), f_open_date)
        ws.merge_range(row, 1, row, 12, 'Opening balance', f_open)
        ws.write(row, 14, '', f_open)
        ws.write(row, 15, '', f_open)
        ws.write_number(row, 16, data['opening_balance'], f_open_num)
        row += 1

        def num(r, c, value):
            if value is None:
                ws.write_blank(r, c, None, f_num)
            else:
                ws.write_number(r, c, value, f_num)

        for line in data['rows']:
            ws.write_datetime(row, 0, fields.Datetime.to_datetime(line['voucher_date']), f_date)
            ws.write(row, 1, line['voucher_no'] or '', f_text)
            ws.write(row, 2, line['remarks'] or '', f_text)
            ws.write(row, 3, line['item_name'] or '', f_text)
            if line['invoice_age'] is None:
                ws.write_blank(row, 4, None, f_center)
            else:
                ws.write_number(row, 4, line['invoice_age'], f_center)
            num(row, 5, line['gross_rate'])
            num(row, 6, line['quantity'])
            if line['discount'] is None:
                ws.write_blank(row, 7, None, f_pct)
            else:
                ws.write_number(row, 7, line['discount'] / 100.0, f_pct)
            num(row, 8, line['net_rate'])
            num(row, 9, line['ex_amount'])
            if line['gst_rate'] is None:
                ws.write_blank(row, 10, None, f_pct)
            else:
                ws.write_number(row, 10, line['gst_rate'] / 100.0, f_pct)
            num(row, 11, line['gst_amount'])
            num(row, 12, line['incl_amount'])
            num(row, 14, line['debit'] or None)
            num(row, 15, line['credit'] or None)
            num(row, 16, line['running_balance'])
            row += 1

        # totals - plain values, same figures as the PDF
        ws.merge_range(row, 0, row, 5, 'TOTAL', f_tot)
        ws.write_number(row, 6, data['total_qty'], f_tot_num)
        ws.write(row, 7, '', f_tot_blank)
        ws.write(row, 8, '', f_tot_blank)
        ws.write_number(row, 9, data['total_ex'], f_tot_num)
        ws.write(row, 10, '', f_tot_blank)
        ws.write_number(row, 11, data['total_gst'], f_tot_num)
        ws.write_number(row, 12, data['total_incl'], f_tot_num)
        ws.write_number(row, 14, data['total_debit'], f_tot_num)
        ws.write_number(row, 15, data['total_credit'], f_tot_num)
        ws.write_number(row, 16, data['closing_balance'], f_tot_num)

        # page setup: A4 landscape, fit to one page wide, header repeats
        ws.set_landscape()
        ws.set_paper(9)
        ws.set_margins(left=0.25, right=0.25, top=0.5, bottom=0.5)
        ws.fit_to_pages(1, 0)
        ws.repeat_rows(first_table_row)
        ws.hide_gridlines(2)

        wb.close()
        return buf.getvalue()

    @staticmethod
    def _logo_scale(logo_b64):
        """Logo ~42px tall / max 120px wide, like the PDF header, instead
        of Excel showing it at its raw pixel size."""
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(base64.b64decode(logo_b64)))
            return min(42.0 / img.height, 120.0 / img.width, 1.0)
        except Exception:
            return 0.3
