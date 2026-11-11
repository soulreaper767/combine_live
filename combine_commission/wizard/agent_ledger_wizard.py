import base64
import io

from odoo import _, fields, models
from odoo.exceptions import UserError

try:
    import xlsxwriter
except ImportError:  # always shipped with Odoo
    xlsxwriter = None

ACCOUNTING_FMT = '_(* #,##0_);_(* \\(#,##0\\);_(* "-"??_);_(@_)'
HEAD_FILL = '#F3F4F6'
INK = '#1F2937'
HAIR = '#E5E7EB'
RULE = '#CBD5E1'

LEDGER_COLS = [('Date', 10.8), ('V. No.', 20), ('Customer / Remarks', 32), ('Contract', 10), ('Item', 22),
               ('Qty', 9), ('Sales Value (Ex. GST)', 14), ('Comm. %', 8), ('', 0.6),
               ('Debit', 13), ('Credit', 13), ('Balance', 14)]
SUMMARY_COLS = [('Commission Agent', 30), ('Opening', 14), ('Commission (net)', 15), ('Paid / Adjusted', 15),
                ('Closing Balance', 15), ('of which Unbilled', 15), ('of which Billed', 15), ('', 0.6),
                ('Not yet booked', 15)]


class CommissionLedgerWizard(models.TransientModel):
    _name = 'combine.commission.ledger.wizard'
    _description = 'Commission Agent Ledger - print options'

    report_type = fields.Selection([('ledger', 'Agent Ledger'), ('summary', 'Agent Outstanding Summary')],
                                   default='ledger', required=True, string='Report')
    agent_ids = fields.Many2many('combine001.commission.agent', 'combine_comm_ledger_agent_rel', 'wizard_id', 'agent_id',
                                 string='Commission Agents', help='Leave empty for all agents.')
    date_from = fields.Date(string='From', required=True,
                            default=lambda self: fields.Date.context_today(self).replace(month=1, day=1))
    date_to = fields.Date(string='To', required=True, default=fields.Date.context_today)

    def _agents(self):
        self.ensure_one()
        return (self.agent_ids or self.env['combine001.commission.agent'].search([])).sorted('name')

    def action_print(self):
        self.ensure_one()
        if self.date_to < self.date_from:
            raise UserError(_('"To" date is before "From" date.'))
        ref = 'combine_commission.action_report_agent_ledger' if self.report_type == 'ledger' \
            else 'combine_commission.action_report_agent_summary'
        return self.env.ref(ref).report_action(self)

    def action_print_xlsx(self):
        self.ensure_one()
        report = self.env['report.combine_commission.agent_ledger_document']
        content = self._xlsx_ledger(report) if self.report_type == 'ledger' else self._xlsx_summary(report)
        name = 'Commission Agent Ledger.xlsx' if self.report_type == 'ledger' else 'Agent Outstanding Summary.xlsx'
        attachment = self.env['ir.attachment'].create({
            'name': name, 'datas': base64.b64encode(content), 'res_model': self._name, 'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {'type': 'ir.actions.act_url', 'url': '/web/content/%s?download=true' % attachment.id,
                'target': 'self'}

    # ------------------------------------------------------------- excel
    def _formats(self, wb):
        base = {'font_name': 'Arial', 'font_size': 9, 'valign': 'vcenter', 'font_color': INK}
        cell = {**base, 'border': 1, 'border_color': HAIR}
        tot = {**base, 'bold': True, 'bg_color': HEAD_FILL, 'top': 1, 'top_color': INK, 'bottom': 6,
               'bottom_color': INK}
        return {
            'co': wb.add_format({**base, 'bold': True, 'font_size': 11}),
            'lbl': wb.add_format({**base, 'font_color': '#6B7280'}),
            'val': wb.add_format({**base, 'bold': True}),
            'title': wb.add_format({**base, 'bold': True, 'font_size': 14, 'align': 'right'}),
            'hdate': wb.add_format({**base, 'num_format': 'dd-mmm-yy', 'align': 'left'}),
            'head': wb.add_format({**base, 'bold': True, 'align': 'center', 'text_wrap': True, 'bg_color': HEAD_FILL,
                                   'top': 1, 'top_color': INK, 'bottom': 2, 'bottom_color': INK, 'left': 1,
                                   'right': 1, 'left_color': RULE, 'right_color': RULE}),
            'date': wb.add_format({**cell, 'num_format': 'dd-mmm-yy', 'align': 'center'}),
            'text': wb.add_format({**cell, 'text_wrap': True, 'valign': 'top'}),
            'center': wb.add_format({**cell, 'align': 'center'}),
            'num': wb.add_format({**cell, 'num_format': ACCOUNTING_FMT}),
            'open': wb.add_format({**cell, 'italic': True, 'font_color': '#4B5563'}),
            'open_num': wb.add_format({**cell, 'italic': True, 'num_format': ACCOUNTING_FMT}),
            'tot': wb.add_format({**tot, 'align': 'center'}),
            'tot_num': wb.add_format({**tot, 'num_format': ACCOUNTING_FMT}),
            'tot_blank': wb.add_format(tot),
            'note': wb.add_format({**base, 'italic': True, 'font_color': '#4B5563'}),
        }

    def _sheet_header(self, ws, f, cols, title, company, date_from, date_to, party=None):
        for col, (_t, width) in enumerate(cols):
            ws.set_column(col, col, width)
        last = len(cols) - 1
        ws.write(0, 0, company.name, f['co'])
        ws.merge_range(0, last - 3, 0, last, title, f['title'])
        row = 1
        if party:
            ws.write(row, 0, 'Agent:', f['lbl'])
            ws.write(row, 1, party, f['val'])
            row += 1
        ws.write(row, 0, 'Period:', f['lbl'])
        ws.write_datetime(row, 1, fields.Datetime.to_datetime(date_from), f['hdate'])
        ws.write(row, 2, 'to')
        ws.write_datetime(row, 3, fields.Datetime.to_datetime(date_to), f['hdate'])
        row += 2
        ws.set_row(row, 26)
        for col, (t, _w) in enumerate(cols):
            if t:
                ws.write(row, col, t, f['head'])
        ws.set_landscape()
        ws.set_paper(9)
        ws.fit_to_pages(1, 0)
        ws.hide_gridlines(2)
        return row + 1

    def _xlsx_ledger(self, report):
        buf = io.BytesIO()
        wb = xlsxwriter.Workbook(buf, {'in_memory': True})
        f = self._formats(wb)
        used = set()
        for agent in self._agents():
            data = report._ledger_data(self, agent)
            name = (agent.name or 'Agent')[:28]
            for ch in '[]:*?/\\':
                name = name.replace(ch, ' ')
            while name in used:
                name = name[:25] + '_'
            used.add(name)
            ws = wb.add_worksheet(name)
            row = self._sheet_header(ws, f, LEDGER_COLS, 'COMMISSION AGENT LEDGER', data['company'],
                                     data['date_from'], data['date_to'], agent.name)
            ws.write_datetime(row, 0, fields.Datetime.to_datetime(data['date_from']), f['date'])
            ws.merge_range(row, 1, row, 7, 'Opening balance', f['open'])
            ws.write(row, 9, '', f['open'])
            ws.write(row, 10, '', f['open'])
            ws.write_number(row, 11, data['opening'], f['open_num'])
            row += 1

            def num(r, c, v):
                if v is None:
                    ws.write_blank(r, c, None, f['num'])
                else:
                    ws.write_number(r, c, v, f['num'])
            for line in data['rows']:
                ws.write_datetime(row, 0, fields.Datetime.to_datetime(line['date']), f['date'])
                ws.write(row, 1, line['voucher'] or '', f['text'])
                ws.write(row, 2, line['customer'] or line['remarks'] or '', f['text'])
                ws.write(row, 3, line['contract'] or '', f['text'])
                ws.write(row, 4, line['item'] or '', f['text'])
                num(row, 5, line['qty'])
                num(row, 6, line['sales'])
                ws.write(row, 7, '' if line['rate'] is None else '%g%%' % line['rate'], f['center'])
                num(row, 9, line['debit'] or None)
                num(row, 10, line['credit'] or None)
                num(row, 11, line['balance'])
                row += 1
            ws.merge_range(row, 0, row, 4, 'TOTAL', f['tot'])
            ws.write_number(row, 5, data['totals']['qty'], f['tot_num'])
            ws.write_number(row, 6, data['totals']['sales'], f['tot_num'])
            ws.write(row, 7, '', f['tot_blank'])
            ws.write_number(row, 9, data['totals']['debit'], f['tot_num'])
            ws.write_number(row, 10, data['totals']['credit'], f['tot_num'])
            ws.write_number(row, 11, data['closing'], f['tot_num'])
            if data['not_booked_count']:
                ws.write(row + 2, 0, 'Not yet booked in the accounts: %s line(s), %s' % (
                    data['not_booked_count'], '{:,.0f}'.format(data['not_booked_amount'])), f['note'])
        wb.close()
        return buf.getvalue()

    def _xlsx_summary(self, report):
        buf = io.BytesIO()
        wb = xlsxwriter.Workbook(buf, {'in_memory': True})
        f = self._formats(wb)
        data = report._summary_data(self)
        ws = wb.add_worksheet('Agent Outstanding')
        row = self._sheet_header(ws, f, SUMMARY_COLS, 'AGENT OUTSTANDING SUMMARY', data['company'],
                                 data['date_from'], data['date_to'])
        keys = ['opening', 'earned', 'paid', 'closing', 'unbilled', 'billed']
        for line in data['rows']:
            ws.write(row, 0, line['agent'], f['text'])
            for i, k in enumerate(keys):
                ws.write_number(row, 1 + i, line[k], f['num'])
            ws.write_number(row, 8, line['not_booked'], f['num'])
            row += 1
        ws.write(row, 0, 'TOTAL', f['tot'])
        for i, k in enumerate(keys):
            ws.write_number(row, 1 + i, data['totals'][k], f['tot_num'])
        ws.write_number(row, 8, data['totals']['not_booked'], f['tot_num'])
        wb.close()
        return buf.getvalue()
