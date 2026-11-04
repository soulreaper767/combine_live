from odoo import api, models
from odoo.tools import float_is_zero, format_date

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
    def _discount_values(self, line, qty, currency, partner):
        """Rate before discount, discount %, discounted rate, gross / discount / net
        value - all excluding sales tax (correct for tax-included prices too)."""
        # gross = the whole line before discount, excl. tax, computed and rounded
        # exactly like Odoo computes the line's own (discounted) net amount
        if line.tax_ids:
            gross = line.tax_ids.compute_all(line.price_unit, currency=currency, quantity=qty,
                                             product=line.product_id, partner=partner)['total_excluded']
        else:
            gross = currency.round(line.price_unit * qty)
        gross_unit = gross / qty if qty else line.price_unit
        net = line.price_subtotal
        return {
            'g_rate': _num(gross_unit, 4 if abs(gross_unit * 100 - round(gross_unit * 100)) > 1e-6 else 2),
            'disc_pct': f'{line.discount:g}%' if line.discount else '-',
            'd_rate': _num(net / qty if qty else 0.0, 2),
            'gross': _num(gross),
            'disc': _num(gross - net),
            '_gross': gross,
            '_disc': gross - net,
        }

    @api.model
    def _discount_totals(self, rows):
        return {'gross_total': _num(sum(r['_gross'] for r in rows)), 'disc_total': _num(sum(r['_disc'] for r in rows))}

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
                **self._discount_values(line, line.quantity, move.currency_id, move.partner_id),
            })
        company_partner = move.company_id.partner_id
        return {
            'title': 'Sales Tax Credit Note' if move.move_type == 'out_refund' else 'Sales Tax Invoice',
            'rows': rows,
            **self._discount_totals(rows),
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
    def _party_box(self, label, partner, extra=None):
        return {'label': label, 'partner': partner.commercial_partner_id, 'address': self._address(partner),
                'ids': self._tax_ids_text(partner), 'extra': extra or []}

    @api.model
    def _order_rows(self, lines, qty_field, currency=None, partner=None):
        rows = []
        for i, line in enumerate(lines, 1):
            rates = line.tax_ids.filtered(lambda t: t.amount_type == 'percent')
            qty = line[qty_field]
            rows.append({
                'sr': i,
                'desc': line.product_id.display_name or line.name or '',
                'note': line.name if line.name and line.product_id and line.name != line.product_id.display_name else '',
                'hs': _field(line.product_id, 'hs_code') or '',
                'qty': _num(qty, 2),
                'uom': line.product_uom_id.name or '',
                'rate': _num(line.price_subtotal / qty if qty else 0.0, 2),
                'ex': _num(line.price_subtotal),
                'tax_rate': ' + '.join(f"{t.amount:g}%" for t in rates) or '-',
                'tax': _num(line.price_total - line.price_subtotal),
                'inc': _num(line.price_total),
                **(self._discount_values(line, qty, currency, partner) if currency else {}),
            })
        return rows

    @api.model
    def _order_totals(self, order, qty):
        return {
            'has_hs': 'hs_code' in self.env['product.product']._fields,
            'qty_total': _num(qty, 2),
            'ex_total': _num(order.amount_untaxed),
            'tax_total': _num(order.amount_tax),
            'inc_total': _num(order.amount_total),
            'words': order.currency_id.amount_to_text(order.amount_total),
        }

    @api.model
    def _po_data(self, order):
        """Request for Quotation (until confirmed) / Purchase Order (after) - Contract layout."""
        lines = order.order_line.filtered(lambda l: not l.display_type)
        confirmed = order.state in ('purchase', 'done')
        company = order.company_id.partner_id
        deliver_to = order.picking_type_id.warehouse_id.partner_id or company
        return {
            'title': 'Purchase Order' if confirmed else 'Request for Quotation',
            'info': [('PO No.' if confirmed else 'RFQ No.', order.name),
                     ('Order Date', format_date(self.env, order.date_order)),
                     ('Expected', format_date(self.env, order.date_planned) if order.date_planned else '-'),
                     ('Payment Terms', order.payment_term_id.name or '-'),
                     ('Buyer', order.user_id.name or '-'),
                     ('Vendor Ref.', order.partner_ref or '-')],
            'boxes': [self._party_box('Vendor', order.partner_id),
                      self._party_box('Buyer / Deliver To', company,
                                      [('Deliver', self._address(deliver_to))] if deliver_to != company else [])],
            'rows': self._order_rows(lines, 'product_qty'),
            **self._order_totals(order, sum(lines.mapped('product_qty'))),
            'terms_label': 'Terms & Conditions',
            'terms': order.note,
            'signatures': [('Prepared by', order.user_id.name or order.create_uid.name), ('Approved by', ''),
                           ('Accepted by Vendor', 'Signature & stamp'), (f'For {order.company_id.name}', 'Authorised signatory')],
            'cancelled': order.state == 'cancel',
        }

    @api.model
    def _picking_data(self, picking):
        """Delivery Challan / Receipt / Transfer - quantities and weights, no prices."""
        code = picking.picking_type_code
        title = {'outgoing': 'Delivery Challan', 'incoming': 'Goods Receipt', 'internal': 'Internal Transfer'}.get(code, 'Transfer')
        moves = picking.move_ids.filtered(lambda m: m.state != 'cancel')
        rows, total_qty, total_wt = [], 0.0, 0.0
        for i, move in enumerate(moves, 1):
            qty = move.quantity if picking.state == 'done' else move.product_uom_qty
            weight = (move.product_id.weight or 0.0) * move.product_uom._compute_quantity(qty, move.product_id.uom_id)
            total_qty += qty
            total_wt += weight
            rows.append([i, move.product_id.display_name, _field(move.product_id, 'hs_code') or '-',
                         _num(move.product_uom_qty, 2), _num(move.quantity, 2), move.product_uom.name, _num(weight, 2)])
        origin = picking.sale_id.name if 'sale_id' in picking._fields and picking.sale_id else picking.origin
        party_label = {'outgoing': 'Deliver To', 'incoming': 'Received From'}.get(code, 'Party')
        return {
            'title': title,
            'info': [({'outgoing': 'Challan No.', 'incoming': 'Receipt No.'}.get(code, 'Transfer No.'), picking.name),
                     ('Date', format_date(self.env, picking.date_done or picking.scheduled_date)),
                     ('Contract / Source', origin or '-'),
                     ('Operation', picking.picking_type_id.name),
                     ('From', picking.location_id.display_name), ('To', picking.location_dest_id.display_name)],
            'boxes': [self._party_box(party_label, picking.partner_id)] if picking.partner_id else [],
            'columns': [('Sr.', 'c'), ('Item', ''), ('HS Code', 'c'), ('Ordered', 'n'), ('Delivered' if code == 'outgoing' else 'Done', 'n'),
                        ('UoM', 'c'), ('Weight', 'n')],
            'rows': rows,
            'totals': {4: _num(total_qty, 2), 6: _num(total_wt, 2)},
            'note': picking.note,
            'signatures': [('Prepared by', picking.create_uid.name), ('Store Incharge', ''), ('Gate Officer', ''),
                           ('Received by' if code == 'outgoing' else 'Checked by', '')],
            'cancelled': picking.state == 'cancel',
        }

    @api.model
    def _order_data(self, order):
        """Contract (before confirmation) / Sales Order (after), same columns as the sales tax invoice."""
        lines = order.order_line.filtered(lambda l: not l.display_type and not l.is_downpayment)
        confirmed = order.state == 'sale'
        extra = [('Deliver', self._address(order.partner_shipping_id))] if order.partner_shipping_id != order.partner_id else []
        info = [('Order No.' if confirmed else 'Contract No.', order.name),
                ('Date', format_date(self.env, order.date_order))]
        if order.validity_date and not confirmed:
            info.append(('Valid Until', format_date(self.env, order.validity_date)))
        info += [('Payment Terms', order.payment_term_id.name or '-'), ('Salesperson', order.user_id.name or '-'),
                 ('Buyer Ref.', order.client_order_ref or '-')]
        return {
            'title': 'Sales Order' if confirmed else 'Contract',
            'info': info,
            'boxes': [self._party_box('Seller', order.company_id.partner_id), self._party_box('Buyer', order.partner_id, extra)],
            'rows': self._order_rows(lines, 'product_uom_qty', order.currency_id, order.partner_id),
            'discount_layout': True,
            **self._order_totals(order, sum(lines.mapped('product_uom_qty'))),
            **self._discount_totals(self._order_rows(lines, 'product_uom_qty', order.currency_id, order.partner_id)),
            'terms_label': 'Terms & Conditions',
            'terms': order.note,
            'signatures': [('Prepared by', order.user_id.name or order.create_uid.name), ('Approved by', ''),
                           ('Accepted by Buyer', 'Signature & stamp'), (f'For {order.company_id.name}', 'Authorised signatory')],
            'cancelled': order.state == 'cancel',
        }

    @api.model
    def _helpers(self):
        return {'voucher_data': self._voucher_data, 'fbr_data': self._fbr_data, 'order_data': self._order_data,
                'po_data': self._po_data, 'picking_data': self._picking_data}


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


class ReportSaleOrder(models.AbstractModel):
    _name = 'report.partner_ledger_qty.report_sale_order'
    _description = 'Custom Reports - Contract / Sales Order'

    @api.model
    def _get_report_values(self, docids, data=None):
        return {'docs': self.env['sale.order'].browse(docids),
                **self.env['partner_ledger_qty.voucher.mixin']._helpers()}


class ReportPurchaseOrder(models.AbstractModel):
    _name = 'report.partner_ledger_qty.report_purchase_order'
    _description = 'Custom Reports - RFQ / Purchase Order'

    @api.model
    def _get_report_values(self, docids, data=None):
        return {'docs': self.env['purchase.order'].browse(docids),
                **self.env['partner_ledger_qty.voucher.mixin']._helpers()}


class ReportPicking(models.AbstractModel):
    _name = 'report.partner_ledger_qty.report_picking'
    _description = 'Custom Reports - Delivery Challan / Transfer'

    @api.model
    def _get_report_values(self, docids, data=None):
        return {'docs': self.env['stock.picking'].browse(docids),
                **self.env['partner_ledger_qty.voucher.mixin']._helpers()}
