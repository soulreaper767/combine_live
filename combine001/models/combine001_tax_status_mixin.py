from odoo import fields, models


class Combine001TaxStatusMixin(models.AbstractModel):
    """Registered/Unregistered status, mirrored from the Customer/Vendor
    master (res.partner's Tax Info tab) onto every document the BRD
    requires it on: Contract/Delivery Order, Delivery Challan, Gate Pass
    and Sales Invoice (BRD sec. 4.3). Each inheriting model
    must already have its own `partner_id` field - this only adds the 3
    related, stored status fields so they're queryable/filterable on the
    document itself instead of always joining back to the partner.

    PRA status is deliberately NOT part of this mixin's automatic
    display: whether to show it on a given document depends on that
    document's own lines (only when a PRA-applicable product is on it -
    see product_template.x_pra_applicable), which differs per model, so
    each inheriting model defines its own `x_show_pra_status` compute.
    """
    _name = 'combine001.tax.status.mixin'
    _description = 'Combine001 Tax Status Mixin'

    # Placeholder only - every inheriting model already has its own real
    # partner_id (sale.order/account.move/stock.picking all carry one
    # natively). Declared here purely so the related fields below can be
    # set up on the abstract model itself (Odoo validates related-field
    # targets against the model they're declared on, abstract or not).
    partner_id = fields.Many2one('res.partner')

    x_gst_status = fields.Selection(
        related='partner_id.x_gst_status', store=True, string='GST Status')
    x_income_tax_status = fields.Selection(
        related='partner_id.x_income_tax_status', store=True, string='Income Tax Status')
    x_pra_status = fields.Selection(
        related='partner_id.x_pra_status', store=True, string='PRA Status')
