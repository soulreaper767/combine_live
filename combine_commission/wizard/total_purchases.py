"""Total Purchases Report (Purchase > Reporting): posted vendor bills (and
vendor refunds / debit notes, as negatives), same layout and columns as the
Total Sales Report; commission from purchase commission lines.
Read-only; rendered by Custom Reports' register engine (house-style PDF/Excel).
"""
from odoo import _, fields, models


class TotalPurchasesWizard(models.TransientModel):
    _name = 'combine.total.purchases.wizard'
    _inherit = 'combine.total.sales.wizard'
    _description = 'Total Purchases Report'
    _register_report_xmlid = 'combine_commission.action_report_total_purchases'

    by_party = fields.Boolean(string='By Vendor', default=True)
    include_refunds = fields.Boolean(string='Include debit notes (vendor refunds)', default=True,
                                     help='Vendor refunds are shown as negative purchases.')
    tax_ids = fields.Many2many('account.tax', 'combine_tpur_tax_rel', 'wizard_id', 'tax_id', string='Tax Rates',
                               domain=[('type_tax_use', '=', 'purchase')], help='Leave empty for all tax rates.')
    agent_ids = fields.Many2many('combine001.commission.agent', 'combine_tpur_agent_rel', 'wizard_id', 'agent_id',
                                 string='Commission Agents', help='Leave empty for all.')
    user_ids = fields.Many2many('res.users', 'combine_tpur_user_rel', 'wizard_id', 'user_id', string='Buyers',
                                help='Leave empty for all.')
    created_by_ids = fields.Many2many('res.users', 'combine_tpur_cuser_rel', 'wizard_id', 'user_id', string='Entries created by',
                                      context={'active_test': False},
                                      help='User who created the bill. Leave empty for all.')

    def _lines(self):
        types = ('in_invoice', 'in_refund') if self.include_refunds else ('in_invoice',)
        domain = [('move_id.move_type', 'in', types), ('move_id.state', '=', 'posted'), ('display_type', '=', 'product'),
                  ('move_id.company_id', '=', self.env.company.id),
                  ('move_id.invoice_date', '>=', self.date_from), ('move_id.invoice_date', '<=', self.date_to)]
        if self.tax_ids:
            domain.append(('tax_ids', 'in', self.tax_ids.ids))
        if self.user_ids:
            domain.append(('move_id.invoice_user_id', 'in', self.user_ids.ids))
        if self.created_by_ids:
            domain.append(('move_id.create_uid', 'in', self.created_by_ids.ids))
        # read with sudo so every internal user can run the report (it is read-only)
        lines = self.env['account.move.line'].sudo().search(domain).sorted(
            lambda l: (l.move_id.invoice_date, l.move_id.name or '', l.id))
        PCL = self.env['combine001.purchase.commission.line'].sudo()
        comm = {c.vendor_bill_line_id.id: c for c in PCL.search([('vendor_bill_line_id', 'in', lines.ids)])}
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
            sign = -1.0 if move.move_type == 'in_refund' else 1.0
            qty = line.quantity * sign
            gross = line.price_unit * line.quantity * sign
            discount = gross * (line.discount or 0.0) / 100.0
            ex = line.price_subtotal * sign
            incl = line.price_total * sign
            out.append({
                'date': move.invoice_date, 'invoice': move.name, 'party': partner.name or '',
                'party_key': partner.id, 'item': line.product_id.display_name or line.name or '',
                'item_key': line.product_id.id or 0, 'uom': line.product_uom_id.name or '',
                'qty': qty, 'rate': line.price_unit, 'disc_pct': '{:g}%'.format(line.discount) if line.discount else '',
                'gross': gross, 'discount': discount, 'ex': ex,
                'tax_pct': ', '.join('{:g}%'.format(t.amount) for t in line.tax_ids) or _('No tax'),
                'tax': incl - ex, 'incl': incl, 'net_rate': (ex / qty) if qty else 0.0,
                'comm_pct': '{:g}%'.format(c.rate) if c else '', 'comm': (c.commission_amount if c else 0.0),
                'agent': c.agent_id.name if c else '',
            })
        return out

    def _dims(self):
        return [(k, _('Vendor') if k == 'party' else label) for k, label in super()._dims()]

    def _columns(self, dims):
        return [(_('Vendor') if key == 'party' else label, kind, key) for label, kind, key in super()._columns(dims)]

    def _register_data(self):
        res = super()._register_data()
        res['title'] = _('Total Purchases Report')
        res['filters'] = [(_('Vendors'), v) if k == _('Parties') else (_('Buyers'), v) if k == _('Salespersons') else
                          ((_('Debit notes'), v) if k == _('Credit notes') else (k, v)) for k, v in res['filters']]
        if res['groups'] and res['groups'][0]['title'] == _('All sales'):
            res['groups'][0]['title'] = _('All purchases')
        return res
