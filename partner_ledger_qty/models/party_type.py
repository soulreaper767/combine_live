from odoo import fields, models


class PartyType(models.Model):
    """User-defined classification of parties (e.g. Local Customer, Export
    Customer, Raw Material Supplier, Stores Supplier, Broker) used to select
    which parties the party-wise reports show."""
    _name = 'combine.party.type'
    _description = 'Party Type'
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    code = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text()
    partner_count = fields.Integer(compute='_compute_partner_count', string='Parties')

    _name_uniq = models.Constraint('UNIQUE(name)', 'A party type with this name already exists.')

    def _compute_partner_count(self):
        counts = dict(self.env['res.partner'].with_context(active_test=False)._read_group(
            [('x_party_type_id', 'in', self.ids)], ['x_party_type_id'], ['__count']))
        for party_type in self:
            party_type.partner_count = counts.get(party_type, 0)

    def action_view_partners(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': self.name, 'res_model': 'res.partner',
                'view_mode': 'list,form', 'domain': [('x_party_type_id', '=', self.id)],
                'context': {'default_x_party_type_id': self.id}}


class ResPartner(models.Model):
    _inherit = 'res.partner'

    x_party_type_id = fields.Many2one('combine.party.type', string='Party Type', index='btree_not_null',
                                      ondelete='restrict', tracking=True,
                                      help='Used to select parties in the party-wise reports.')
