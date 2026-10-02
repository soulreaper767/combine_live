from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # -- Tax Info tab ------------------------------------------------------
    # BRD "BRD for sales.docx" section 4 asked for two checkboxes
    # (Registered / Unregistered) that flow onto every downstream document.
    # Refined per follow-up request into a proper Tax Info tab with a
    # separate status per tax regime instead of one flat pair of
    # checkboxes: GST status is the direct implementation of that BRD
    # requirement; Income Tax and PRA are the same idea extended to the
    # other two compliance regimes this business actually deals with.
    x_gst_status = fields.Selection([
        ('registered', 'Registered'),
        ('unregistered', 'Unregistered'),
    ], string='GST Status', default='unregistered', tracking=True,
        help='Sales Tax (GST) registration status. Flows onto Contracts, '
             'Delivery Orders, Delivery Challans, Gate Passes and Sales '
             'Invoices.')
    x_gst_number = fields.Char(string='GST / STRN Number')

    x_income_tax_status = fields.Selection([
        ('filer', 'Filer'),
        ('non_filer', 'Non-Filer'),
    ], string='Income Tax Status', default='non_filer', tracking=True,
        help='Income Tax (FBR Active Taxpayer List) status - relevant for '
             'withholding tax. Flows onto documents the same way GST '
             'status does.')
    x_income_tax_number = fields.Char(string='NTN / Income Tax Number')

    x_pra_status = fields.Selection([
        ('registered', 'Registered'),
        ('unregistered', 'Unregistered'),
    ], string='PRA Status', default='unregistered', tracking=True,
        help='Punjab Revenue Authority (services sales tax) registration '
             'status. Only shown on a document at all when that document '
             'has at least one line for a product flagged '
             '"PRA Applicable (Service)" in its own Sales tab - most of '
             'this business is goods (GST), not services (PRA).')
    x_pra_number = fields.Char(string='PRA Registration Number')
