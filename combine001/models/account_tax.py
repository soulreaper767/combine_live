from odoo import fields, models


class AccountTax(models.Model):
    _inherit = 'account.tax'

    x_combine001_gst = fields.Boolean(
        string='Combine001 GST Tax', default=False,
        help='Marks this as one of the 4 GST taxes this module manages '
             '(Sale/Purchase x 18%/22%), so the GST Saving calculation on '
             'invoice/bill posting knows which taxes count as "GST was '
             'charged" versus falling back to the notional GST-saved '
             'calculation.',
    )

    def _combine001_swap_gst_for_buyer(self, partner, company):
        """If this tax set includes one of Combine001's own SALE-side GST
        taxes, swap it for the rate matching the buyer's GST registration
        status (Tax Info tab): 18% if Registered, 22% if Unregistered -
        FBR charges a higher rate on supplies to unregistered buyers, so
        this is a real rate rule, not just a display default. Purchase-
        side GST (what a vendor charges us) is left untouched - "buyer"
        here always means our own customer.
        """
        gst_tax = self.filtered(lambda t: t.x_combine001_gst and t.type_tax_use == 'sale')
        if not gst_tax:
            return self
        rate = 22.0 if (partner and partner.x_gst_status == 'unregistered') else 18.0
        if gst_tax[0].amount == rate:
            return self
        replacement = self.env['account.tax'].search([
            ('company_id', '=', company.id), ('type_tax_use', '=', 'sale'),
            ('amount', '=', rate), ('x_combine001_gst', '=', True),
        ], limit=1)
        if not replacement:
            return self
        return (self - gst_tax) | replacement
