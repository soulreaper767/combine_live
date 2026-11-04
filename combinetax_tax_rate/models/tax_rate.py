from odoo import api, fields, models


def _rates(taxes_per_line):
    """(highest rate, "18%, 22%") from the percentage taxes of each line."""
    per_line, distinct = [], set()
    for taxes in taxes_per_line:
        percent = taxes.filtered(lambda t: t.amount_type == 'percent')
        per_line.append(sum(percent.mapped('amount')))
        distinct.update(percent.mapped('amount'))
    text = ', '.join(f'{rate:g}%' for rate in sorted(distinct))
    return (max(per_line) if per_line else 0.0), text


class TaxRateMixin(models.AbstractModel):
    _name = 'combinetax.tax.rate.mixin'
    _description = 'Tax rate columns'

    x_tax_rate = fields.Float(string='Tax Rate %', digits=(5, 2), compute='_compute_x_tax_rate', store=True,
                              aggregator='max', help='Highest sales tax rate on the lines.')
    x_tax_rates = fields.Char(string='Tax Rates', compute='_compute_x_tax_rate', store=True,
                              help='Every sales tax rate used on the lines.')

    def _tax_rate_line_taxes(self):
        raise NotImplementedError

    def _compute_x_tax_rate(self):
        for record in self:
            record.x_tax_rate, record.x_tax_rates = _rates(record._tax_rate_line_taxes())


class SaleOrder(models.Model):
    _name = 'sale.order'
    _inherit = ['sale.order', 'combinetax.tax.rate.mixin']

    @api.depends('order_line.tax_ids.amount', 'order_line.tax_ids.amount_type', 'order_line.display_type')
    def _compute_x_tax_rate(self):
        return super()._compute_x_tax_rate()

    def _tax_rate_line_taxes(self):
        return [line.tax_ids for line in self.order_line if not line.display_type]


class PurchaseOrder(models.Model):
    _name = 'purchase.order'
    _inherit = ['purchase.order', 'combinetax.tax.rate.mixin']

    @api.depends('order_line.tax_ids.amount', 'order_line.tax_ids.amount_type', 'order_line.display_type')
    def _compute_x_tax_rate(self):
        return super()._compute_x_tax_rate()

    def _tax_rate_line_taxes(self):
        return [line.tax_ids for line in self.order_line if not line.display_type]


class AccountMove(models.Model):
    _name = 'account.move'
    _inherit = ['account.move', 'combinetax.tax.rate.mixin']

    @api.depends('invoice_line_ids.tax_ids.amount', 'invoice_line_ids.tax_ids.amount_type', 'invoice_line_ids.display_type')
    def _compute_x_tax_rate(self):
        return super()._compute_x_tax_rate()

    def _tax_rate_line_taxes(self):
        return [line.tax_ids for line in self.invoice_line_ids if line.display_type == 'product']
