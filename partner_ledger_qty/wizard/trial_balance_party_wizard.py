import base64
import io

from odoo import fields, models

from .partner_statement_wizard import ACCOUNTING_FMT, HAIR, HEAD_FILL, INK, RULE, PartnerStatementWizard

try:
    import xlsxwriter
except ImportError:  # always shipped with Odoo, guard only for linters
    xlsxwriter = None

AMOUNT_KEYS = ('open_dr', 'open_cr', None, 'dr', 'cr', None, 'close_dr', 'close_cr')


class TrialBalancePartyWizard(models.TransientModel):
    """Entry point: Accounting > Reporting > Trial Balance with Party -
    pick a date range, then Generate Report (PDF) or Generate Excel."""
    _name = 'trial.balance.party.wizard'
    _description = 'Trial Balance with Party - print options'

    date_from = fields.Date(string='From', required=True,
                             default=lambda self: fields.Date.context_today(self).replace(month=1, day=1))
    date_to = fields.Date(string='To', required=True, default=fields.Date.context_today)
    hide_zero = fields.Boolean(string='Hide zero lines', default=True)

    def action_print(self):
        self.ensure_one()
        return self.env.ref('partner_ledger_qty.action_report_trial_balance_party').report_action(self)

    def action_print_xlsx(self):
        self.ensure_one()
        data = self.env['report.partner_ledger_qty.trial_balance_party_document']._get_tb_data(self)
        attachment = self.env['ir.attachment'].create({
            'name': 'Trial Balance with Party %s to %s.xlsx' % (self.date_from, self.date_to),
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
        ws = wb.add_worksheet('Trial Balance')

        base = {'font_name': 'Arial', 'font_size': 9, 'valign': 'vcenter', 'font_color': INK}
        f_co = wb.add_format({**base, 'bold': True, 'font_size': 11})
        f_lbl = wb.add_format({**base, 'font_color': '#6B7280'})
        f_txt = wb.add_format(base)
        f_date_hdr = wb.add_format({**base, 'num_format': 'd-mmm-yy', 'align': 'left'})
        f_title = wb.add_format({**base, 'bold': True, 'font_size': 14, 'align': 'right'})
        f_sub = wb.add_format({**base, 'font_size': 8, 'font_color': '#6B7280', 'align': 'right'})
        head = {**base, 'bold': True, 'align': 'center', 'text_wrap': True, 'bg_color': HEAD_FILL,
                'left': 1, 'right': 1, 'left_color': RULE, 'right_color': RULE}
        f_head_top = wb.add_format({**head, 'top': 1, 'top_color': INK, 'bottom': 1, 'bottom_color': RULE})
        f_head = wb.add_format({**head, 'bottom': 2, 'bottom_color': INK})
        f_head_both = wb.add_format({**head, 'top': 1, 'top_color': INK, 'bottom': 2, 'bottom_color': INK})

        cell = {**base, 'border': 1, 'border_color': HAIR}
        f_code = wb.add_format(cell)
        f_name = wb.add_format(cell)
        f_num = wb.add_format({**cell, 'num_format': ACCOUNTING_FMT})
        ctl = {**cell, 'bold': True, 'bg_color': '#FAFAFA'}
        f_ctl = wb.add_format(ctl)
        f_ctl_num = wb.add_format({**ctl, 'num_format': ACCOUNTING_FMT})
        pty = {**cell, 'font_color': '#374151'}
        f_pty = wb.add_format({**pty, 'indent': 2})
        f_pty_num = wb.add_format({**pty, 'num_format': ACCOUNTING_FMT})
        tot = {**base, 'bold': True, 'bg_color': HEAD_FILL, 'top': 1, 'top_color': INK,
               'bottom': 6, 'bottom_color': INK}
        f_tot = wb.add_format({**tot, 'align': 'center'})
        f_tot_num = wb.add_format({**tot, 'num_format': ACCOUNTING_FMT})

        widths = [12, 44, 14, 14, 0.6, 14, 14, 0.6, 14, 14]
        for col, w in enumerate(widths):
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
        ws.merge_range(row, 6, row, 9, 'TRIAL BALANCE WITH PARTY', f_title)
        ws.write(row + 1, 0, 'Period:', f_lbl)
        ws.write_datetime(row + 1, 1, fields.Datetime.to_datetime(data['date_from']), f_date_hdr)
        ws.merge_range(row + 1, 6, row + 1, 9, 'Amounts in %s' % company.currency_id.name, f_sub)
        ws.write(row + 2, 0, 'to', f_lbl)
        ws.write_datetime(row + 2, 1, fields.Datetime.to_datetime(data['date_to']), f_date_hdr)

        row += 4
        ws.merge_range(row, 0, row + 1, 0, 'Code', f_head_both)
        ws.merge_range(row, 1, row + 1, 1, 'Account / Party', f_head_both)
        for col, title in ((2, 'Opening Balance'), (5, 'Period'), (8, 'Closing Balance')):
            ws.merge_range(row, col, row, col + 1, title, f_head_top)
            ws.write(row + 1, col, 'Debit', f_head)
            ws.write(row + 1, col + 1, 'Credit', f_head)
        ws.freeze_panes(row + 2, 0)
        header_rows = (row, row + 1)
        row += 2

        for r in data['rows']:
            if r['kind'] == 'control':
                f_t, f_n = f_ctl, f_ctl_num
            elif r['kind'] == 'party':
                f_t, f_n = f_pty, f_pty_num
            else:
                f_t, f_n = f_name, f_num
            ws.write(row, 0, r['code'] or '', f_t if r['kind'] == 'control' else f_code)
            ws.write(row, 1, r['name'] or '', f_t)
            for col, key in enumerate(AMOUNT_KEYS, start=2):
                if key:
                    ws.write_number(row, col, r[key], f_n)
            row += 1

        ws.merge_range(row, 0, row, 1, 'TOTAL', f_tot)
        for col, key in enumerate(AMOUNT_KEYS, start=2):
            if key:
                ws.write_number(row, col, data['totals'][key], f_tot_num)

        ws.set_landscape()
        ws.set_paper(9)
        ws.set_margins(left=0.25, right=0.25, top=0.5, bottom=0.5)
        ws.fit_to_pages(1, 0)
        ws.repeat_rows(*header_rows)
        ws.hide_gridlines(2)
        wb.close()
        return buf.getvalue()
