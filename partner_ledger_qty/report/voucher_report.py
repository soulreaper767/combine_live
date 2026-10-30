from odoo import api, models
from odoo.tools import float_is_zero

INVOICE_TITLES = {
    'out_invoice': 'Sales Voucher',
    'out_refund': 'Credit Note Voucher',
    'in_invoice': 'Purchase Voucher',
    'in_refund': 'Debit Note Voucher',
    'out_receipt': 'Sales Receipt Voucher',
    'in_receipt': 'Purchase Receipt Voucher',
}


def _num(value, digits=2):
    """1,234.50 / (1,234.50) for negatives / "-" for zero."""
    if value is None:
        return ''
    if float_is_zero(value, precision_digits=digits):
        return '-'
    text = f"{abs(value):,.{digits}f}"
    return f"({text})" if value < 0 else text


def _field(record, name):
    """Value of an optional field (e.g. the NTN/STRN fields another module
    adds to partners) - blank when that field isn't installed."""
    return record[name] if record and name in record._fields else False


class VoucherReportMixin(models.AbstractModel):
    """Shared data for the voucher and sales tax invoice prints."""
    _name = 'partner_ledger_qty.voucher.mixin'
    _description = 'Custom Reports - voucher print helpers'

    @api.model
    def _voucher_title(self, move):
        if move.move_type in INVOICE_TITLES:
            return INVOICE_TITLES[move.move_type]
        journal_type = move.journal_id.type
        if journal_type in ('bank', 'cash'):
            payment = move.origin_payment_id if 'origin_payment_id' in move._fields else False
            if payment:
                inflow = payment.payment_type == 'inbound'
            else:
                liquidity = move.line_ids.filtered(lambda l: l.account_id.account_type == 'asset_cash')
                inflow = sum(liquidity.mapped('balance')) >= 0
            kind = 'Bank' if journal_type == 'bank' else 'Cash'
            return f"{kind} {'Receipt' if inflow else 'Payment'} Voucher"
        return 'Journal Voucher'

    @api.model
    def _voucher_data(self, move):
        lines = move.line_ids.filtered(lambda l: l.display_type not in ('line_section', 'line_note')
                                       and (l.debit or l.credit)).sorted(lambda l: (-l.debit, l.id))
        total_debit = sum(lines.mapped('debit'))
        total_credit = sum(lines.mapped('credit'))
        partners = lines.partner_id.commercial_partner_id
        currency = move.company_id.currency_id
        return {
            'title': self._voucher_title(move),
            'lines': [{
                'sr': i,
                'code': line.account_id.code or '',
                'account': line.account_id.name or '',
                'partner': line.partner_id.commercial_partner_id.name or '',
                'label': line.name or '',
                'debit': _num(line.debit),
                'credit': _num(line.credit),
            } for i, line in enumerate(lines, 1)],
            'total_debit': _num(total_debit),
            'total_credit': _num(total_credit),
            'words': currency.amount_to_text(total_debit) if total_debit else '',
            'partner': partners if len(partners) == 1 else False,
            'state': dict(move._fields['state'].selection).get(move.state, ''),
        }

    @api.model
    def _tax_ids_text(self, partner):
        """NTN / STRN / registration status for the FBR particulars."""
        partner = partner.commercial_partner_id
        status = _field(partner, 'x_gst_status')
        return {
            'ntn': _field(partner, 'x_income_tax_number') or partner.vat or '',
            'strn': _field(partner, 'x_gst_number') or '',
            'status': dict(partner._fields['x_gst_status'].selection).get(status, '') if status else '',
        }

    @api.model
    def _address(self, partner):
        parts = [partner.street, partner.street2, partner.city,
                 partner.state_id.name, partner.zip, partner.country_id.name]
        return ', '.join(p for p in parts if p)

    @api.model
    def _fbr_data(self, move):
        lines = move.invoice_line_ids.filtered(lambda l: l.display_type == 'product')
        rows = []
        for i, line in enumerate(lines, 1):
            rates = line.tax_ids.filtered(lambda t: t.amount_type == 'percent')
            unit_ex = line.price_subtotal / line.quantity if line.quantity else 0.0
            rows.append({
                'sr': i,
                'desc': line.product_id.display_name or line.name or '',
                'note': line.name if line.name and line.product_id and line.name != line.product_id.display_name else '',
                'hs': _field(line.product_id, 'hs_code') or '',
                'qty': _num(line.quantity, 2),
                'uom': line.product_uom_id.name or '',
                'rate': _num(unit_ex, 2),
                'ex': _num(line.price_subtotal),
                'tax_rate': ' + '.join(f"{t.amount:g}%" for t in rates) or '-',
                'tax': _num(line.price_total - line.price_subtotal),
                'inc': _num(line.price_total),
            })
        company_partner = move.company_id.partner_id
        return {
            'title': 'Sales Tax Credit Note' if move.move_type == 'out_refund' else 'Sales Tax Invoice',
            'rows': rows,
            # column shown whenever products carry an HS Code field at all
            'has_hs': 'hs_code' in self.env['product.product']._fields,
            'qty_total': _num(sum(lines.mapped('quantity')), 2),
            'ex_total': _num(move.amount_untaxed),
            'tax_total': _num(move.amount_tax),
            'inc_total': _num(move.amount_total),
            'words': move.currency_id.amount_to_text(move.amount_total),
            'supplier': company_partner,
            'supplier_address': self._address(company_partner),
            'supplier_ids': self._tax_ids_text(company_partner),
            'buyer': move.partner_id.commercial_partner_id,
            'buyer_address': self._address(move.partner_id),
            'buyer_ids': self._tax_ids_text(move.partner_id),
            'challan': _field(move, 'x_delivery_challan_id').name if _field(move, 'x_delivery_challan_id') else '',
        }

    @api.model
    def _helpers(self):
        return {'voucher_data': self._voucher_data, 'fbr_data': self._fbr_data}


class ReportVoucher(models.AbstractModel):
    _name = 'report.partner_ledger_qty.report_voucher'
    _description = 'Custom Reports - Voucher'

    @api.model
    def _get_report_values(self, docids, data=None):
        return {'docs': self.env['account.move'].browse(docids),
                **self.env['partner_ledger_qty.voucher.mixin']._helpers()}


class ReportPaymentVoucher(models.AbstractModel):
    _name = 'report.partner_ledger_qty.report_payment_voucher'
    _description = 'Custom Reports - Payment Voucher'

    @api.model
    def _get_report_values(self, docids, data=None):
        return {'docs': self.env['account.payment'].browse(docids),
                **self.env['partner_ledger_qty.voucher.mixin']._helpers()}


class ReportFbrInvoice(models.AbstractModel):
    _name = 'report.partner_ledger_qty.report_fbr_invoice'
    _description = 'Custom Reports - Sales Tax Invoice (FBR)'

    @api.model
    def _get_report_values(self, docids, data=None):
        return {'docs': self.env['account.move'].browse(docids),
                **self.env['partner_ledger_qty.voucher.mixin']._helpers()}
