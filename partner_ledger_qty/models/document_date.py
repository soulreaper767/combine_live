from odoo import api, fields, models

HELP = ('Date of the document itself (as signed / issued). Odoo\'s own Order Date changes to the moment of '
        'confirmation; prints and the status reports use this date when it is set.')


class DocumentDateMixin(models.AbstractModel):
    """Document Date on contracts and purchase orders. The default lives in
    default_get / create, not on the field: a field default would be written
    into every existing order when the column is added."""
    _name = 'partner_ledger_qty.document.date.mixin'
    _description = 'Document Date'

    x_document_date = fields.Date(string='Document Date', copy=False, tracking=True, help=HELP)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'x_document_date' in fields_list and not res.get('x_document_date'):
            res['x_document_date'] = fields.Date.context_today(self)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('x_document_date'):
                # an order created with its own date (e.g. synced from the Master) keeps that day
                when = vals.get('date_order')
                vals['x_document_date'] = fields.Date.context_today(self, fields.Datetime.to_datetime(when)) if when                     else fields.Date.context_today(self)
        return super().create(vals_list)

    def _document_date(self):
        self.ensure_one()
        return self.x_document_date or fields.Date.context_today(self, self.date_order)


class SaleOrder(models.Model):
    _name = 'sale.order'
    _inherit = ['sale.order', 'partner_ledger_qty.document.date.mixin']


class PurchaseOrder(models.Model):
    _name = 'purchase.order'
    _inherit = ['purchase.order', 'partner_ledger_qty.document.date.mixin']
