from odoo import fields, models

CHARGE_BASIS = [
    ('input', 'Per unit sent'),
    ('output', 'Per unit received'),
    ('fixed', 'Fixed amount'),
]
RECOVERY_BASIS = [
    ('input_cost', 'At the cost of the material sent'),
    ('fixed', 'At a fixed rate per unit'),
    ('none', 'No recovery'),
]


class ConversionProcessCategory(models.Model):
    _name = 'combine.conversion.category'
    _description = 'Conversion Process Category'
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    code = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text()
    charge_account_id = fields.Many2one(
        'account.account', string='Charges Account', company_dependent=True,
        help='Account for the processing charges on vendor bills. Empty: the account of the '
             '"Conversion Charges" product.')
    recovery_account_id = fields.Many2one(
        'account.account', string='Wastage Recovery Account', company_dependent=True,
        help='Account for excess-wastage recoveries on vendor debit notes. Empty: same as charges.')
    process_ids = fields.One2many('combine.conversion.process', 'category_id', string='Processes')


class ConversionProcess(models.Model):
    _name = 'combine.conversion.process'
    _description = 'Conversion Process'
    _order = 'category_id, sequence, name'

    name = fields.Char(required=True, translate=True)
    category_id = fields.Many2one('combine.conversion.category', required=True, ondelete='restrict')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    vendor_id = fields.Many2one('res.partner', string='Usual Vendor')
    output_product_id = fields.Many2one(
        'product.product', string='Usual Output Item', domain=[('is_storable', '=', True)])
    standard_yield = fields.Float(
        string='Standard Yield %', default=100.0, digits=(5, 2),
        help='Output expected per 100 units sent, e.g. 97 means 3% normal wastage.')
    wastage_tolerance = fields.Float(
        string='Wastage Tolerance %', digits=(5, 2),
        help='Extra wastage (in % of what was sent) accepted before anything is recovered from the vendor.')
    recovery_basis = fields.Selection(RECOVERY_BASIS, string='Excess Wastage Recovery', default='input_cost', required=True)
    recovery_rate = fields.Float(string='Recovery Rate / Unit', digits='Product Price')
    waste_product_id = fields.Many2one('product.product', string='Waste Item', domain=[('is_storable', '=', True)],
                                       help='Saleable waste the vendor returns (optional).')
    waste_rate = fields.Float(string='Waste Value / Unit', digits='Product Price')
    charge_line_ids = fields.One2many('combine.conversion.process.charge', 'process_id', string='Charges')
    note = fields.Text()


class ConversionProcessCharge(models.Model):
    _name = 'combine.conversion.process.charge'
    _description = 'Conversion Process Charge'
    _order = 'sequence, id'

    process_id = fields.Many2one('combine.conversion.process', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Charge', required=True)
    basis = fields.Selection(CHARGE_BASIS, required=True, default='input')
    rate = fields.Float(string='Rate', digits='Product Price', help='Per unit of measure, or the amount for a fixed charge.')
