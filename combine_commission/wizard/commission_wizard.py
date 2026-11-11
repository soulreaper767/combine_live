from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CommissionSettlementWizard(models.TransientModel):
    """Commission Settlement: an agent's commission for a period (or the
    lines selected in the commission report) into one commission bill."""
    _name = 'combine.commission.settlement.wizard'
    _description = 'Commission Settlement'

    agent_id = fields.Many2one('combine001.commission.agent', string='Commission Agent')
    date_from = fields.Date(string='Invoices from')
    date_to = fields.Date(string='Invoices to', default=fields.Date.context_today)
    line_ids = fields.Many2many('combine001.commission.line', 'combine_comm_settle_line_rel', 'wizard_id', 'line_id',
                                string='Commission to bill')
    amount_total = fields.Monetary(compute='_compute_amount_total', string='Total')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get('active_model') == 'combine001.commission.line' and self.env.context.get('active_ids'):
            lines = self.env['combine001.commission.line'].browse(self.env.context['active_ids'])
            lines = lines.filtered(lambda l: l._x_state() in ('unbilled', 'not_booked') and l.payment_state != 'paid')
            res['line_ids'] = [(6, 0, lines.ids)]
            if len(lines.agent_id) == 1:
                res['agent_id'] = lines.agent_id.id
        return res

    @api.depends('line_ids')
    def _compute_amount_total(self):
        for wiz in self:
            wiz.amount_total = sum(wiz.line_ids.mapped('commission_amount'))

    @api.onchange('agent_id', 'date_from', 'date_to')
    def _onchange_load_lines(self):
        if not self.agent_id:
            return
        domain = [('agent_id', '=', self.agent_id.id)]
        if self.date_from:
            domain.append(('date', '>=', self.date_from))
        if self.date_to:
            domain.append(('date', '<=', self.date_to))
        lines = self.env['combine001.commission.line'].search(domain, order='date, id').filtered(
            lambda l: l._x_state() in ('unbilled', 'not_booked') and l.payment_state != 'paid')
        self.line_ids = [(6, 0, lines.ids)]

    def action_create_bill(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Select the commission to bill.'))
        ref = False
        if self.agent_id and (self.date_from or self.date_to):
            ref = _('Commission %(agent)s - %(f)s to %(t)s', agent=self.agent_id.name,
                    f=self.date_from and self.date_from.strftime('%d-%b-%y') or '...',
                    t=self.date_to and self.date_to.strftime('%d-%b-%y') or '...')
        bills = self.line_ids._combine_bill(ref=ref)
        return self.env['combine001.commission.line']._action_open_bills(bills)


class CommissionBookWizard(models.TransientModel):
    """Book Commission (Finance Manager): bring commission of invoices posted
    before this module into the accounts without billing it yet. Nothing
    is booked unless a Finance Manager runs this."""
    _name = 'combine.commission.book.wizard'
    _description = 'Book Commission'

    date = fields.Date(required=True, default=fields.Date.context_today, string='Booking Date')
    agent_ids = fields.Many2many('combine001.commission.agent', 'combine_comm_book_agent_rel', 'wizard_id', 'agent_id',
                                 string='Commission Agents', help='Leave empty for all agents.')
    line_ids = fields.Many2many('combine001.commission.line', 'combine_comm_book_line_rel', 'wizard_id', 'line_id', compute='_compute_line_ids', string='To book')
    amount_total = fields.Monetary(compute='_compute_line_ids', string='Total')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)

    @api.depends('agent_ids')
    def _compute_line_ids(self):
        for wiz in self:
            domain = [('agent_id', 'in', wiz.agent_ids.ids)] if wiz.agent_ids else []
            lines = self.env['combine001.commission.line'].search(domain, order='date, id').filtered(
                lambda l: l._x_state() == 'not_booked' and l.payment_state != 'paid')
            wiz.line_ids = lines
            wiz.amount_total = sum(lines.mapped('commission_amount'))

    def action_book(self):
        self.ensure_one()
        if not (self.env.user.has_group('account.group_account_manager')
                or self.env.user.has_group('combine_commission.group_commission_biller')):
            raise UserError(_('Only a Finance Manager or a user with Commission: Book & Bill can book commission.'))
        if not self.line_ids:
            raise UserError(_('There is no unbooked commission.'))
        self.line_ids.agent_id.filtered(lambda a: not a.partner_id).action_combine_create_party()
        self.line_ids._combine_book(date=self.date)
        action = self.env['ir.actions.act_window']._for_xml_id('combine001.action_commission_line')
        action['domain'] = [('id', 'in', self.line_ids.ids)]
        action['context'] = {}
        return action
