from odoo import _, fields, models


class AgentLedgerReport(models.AbstractModel):
    """Commission Agent Ledger - same layout as the Partner Ledger Print.

    Read straight from the posted books (the agent's party on the Unbilled
    Commission account and on its payable account), so the balance always
    agrees with the general ledger:
    - commission booked: one row per commission line (invoice, customer,
      contract, item, qty, sales value excl. GST, rate) - credit;
    - reversals (credit notes, invoices reset to draft): debit;
    - commission bills: shown as a row, no effect on the balance (the
      amount only moves from unbilled to payable);
    - payments and any other entries: debit / credit as posted.
    Balance = amount owed to the agent.
    """
    _name = 'report.combine_commission.agent_ledger_document'
    _description = 'Commission Agent Ledger'

    def _get_report_values(self, docids, data=None):
        wizard = self.env['combine.commission.ledger.wizard'].browse(docids)
        fmt = self.env['report.partner_ledger_qty.partner_statement_document']
        return {
            'doc_ids': docids,
            'doc_model': 'combine.commission.ledger.wizard',
            'docs': wizard,
            'ledger_data': self._ledger_data,
            'summary_data': self._summary_data,
            'fmt_amount': fmt._fmt_amount,
            'fmt_percent': fmt._fmt_percent,
            'fmt_rate': lambda v: '' if v is None else ('{:g}'.format(v) + '%'),
        }

    # ------------------------------------------------------------ helpers
    def _accounts(self, agent):
        company = agent.company_id or self.env.company
        _expense, accrual, _journal = company._combine_commission_setup()
        partner = agent.partner_id.with_company(company)
        payable = partner.property_account_payable_id if partner else self.env['account.account']
        return accrual, payable

    def _base_domain(self, agent):
        accrual, payable = self._accounts(agent)
        return [('partner_id', '=', agent.partner_id.id), ('account_id', 'in', (accrual | payable).ids),
                ('parent_state', '=', 'posted')]

    def _not_booked(self, agent, date_to):
        lines = self.env['combine001.commission.line'].search(
            [('agent_id', '=', agent.id), ('date', '<=', date_to)]).filtered(
            lambda l: l._x_state() == 'not_booked')
        return len(lines), sum(lines.mapped('commission_amount'))

    # ------------------------------------------------------------- ledger
    def _ledger_data(self, wizard, agent):
        AML = self.env['account.move.line']
        CL = self.env['combine001.commission.line']
        date_from, date_to = wizard.date_from, wizard.date_to
        rows, opening = [], 0.0
        if agent.partner_id:
            dom = self._base_domain(agent)
            opening = -sum(AML.search(dom + [('date', '<', date_from)]).mapped('balance'))
            period = AML.search(dom + [('date', '>=', date_from), ('date', '<=', date_to)], order='date, move_id, id')
            moves = period.move_id.sorted(lambda m: (m.date, m.id))
            for move in moves:
                mls = period.filtered(lambda l: l.move_id == move)
                cls = CL.search([('x_accrual_move_id', '=', move.id)], order='date, id') \
                    if move.x_commission_kind == 'booking' else CL
                booked = -sum(mls.mapped('balance'))
                itemize = cls and abs(sum(cls.mapped('commission_amount')) - booked) < 0.01
                if itemize:
                    for cl in cls:
                        amount = cl.commission_amount
                        sales_value = cl.invoice_line_id.price_subtotal
                        if cl.invoice_id.move_type == 'out_refund':
                            sales_value = -sales_value
                        rows.append({
                            'date': move.date, 'voucher': cl.invoice_id.name, 'ref': move.name,
                            'customer': cl.partner_id.name or '', 'contract': cl.sale_order_id.name or '',
                            'item': cl.product_id.display_name or '', 'qty': cl.invoice_line_id.quantity,
                            'sales': sales_value, 'rate': cl.rate, 'remarks': '',
                            'debit': -amount if amount < 0 else 0.0, 'credit': amount if amount > 0 else 0.0,
                        })
                elif move.x_is_commission_bill:
                    net = -sum(mls.mapped('balance'))
                    rows.append({
                        'date': move.date, 'voucher': move.name, 'ref': move.ref or '', 'customer': '', 'contract': '',
                        'item': '', 'qty': None, 'sales': None, 'rate': None,
                        'remarks': _('Commission bill %(amt)s - moved from unbilled to payable',
                                     amt='{:,.0f}'.format(move.amount_total)),
                        'debit': -net if net < 0 else 0.0, 'credit': net if net > 0 else 0.0,
                    })
                else:
                    for ml in mls:
                        rows.append({
                            'date': ml.date, 'voucher': move.name, 'ref': move.ref or '', 'customer': '',
                            'contract': '', 'item': '', 'qty': None, 'sales': None, 'rate': None,
                            'remarks': ml.name or move.ref or '',
                            'debit': ml.debit, 'credit': ml.credit,
                        })
        running = opening
        tot = {'debit': 0.0, 'credit': 0.0, 'qty': 0.0, 'sales': 0.0}
        for row in rows:
            running += row['credit'] - row['debit']
            row['balance'] = running
            for k in tot:
                tot[k] += row[k] or 0.0
        nb_count, nb_amount = self._not_booked(agent, date_to)
        return {
            'company': agent.company_id or self.env.company, 'agent': agent, 'partner': agent.partner_id,
            'date_from': date_from, 'date_to': date_to, 'opening': opening, 'rows': rows,
            'closing': running, 'totals': tot, 'not_booked_count': nb_count, 'not_booked_amount': nb_amount,
        }

    # ------------------------------------------------------------ summary
    def _summary_data(self, wizard):
        AML = self.env['account.move.line']
        agents = wizard.agent_ids or self.env['combine001.commission.agent'].search([])
        rows = []
        for agent in agents.sorted('name'):
            vals = {'agent': agent.name, 'opening': 0.0, 'earned': 0.0, 'paid': 0.0, 'closing': 0.0,
                    'unbilled': 0.0, 'billed': 0.0}
            if agent.partner_id:
                accrual, payable = self._accounts(agent)
                dom = self._base_domain(agent)
                vals['opening'] = -sum(AML.search(dom + [('date', '<', wizard.date_from)]).mapped('balance'))
                upto = AML.search(dom + [('date', '<=', wizard.date_to)])
                vals['closing'] = -sum(upto.mapped('balance'))
                vals['unbilled'] = -sum(upto.filtered(lambda l: l.account_id == accrual).mapped('balance'))
                vals['billed'] = vals['closing'] - vals['unbilled']
                period = AML.search(dom + [('date', '>=', wizard.date_from), ('date', '<=', wizard.date_to)])
                vals['earned'] = -sum(period.filtered(
                    lambda l: l.move_id.x_commission_kind in ('booking', 'reversal')).mapped('balance'))
                vals['paid'] = vals['opening'] + vals['earned'] - vals['closing']
            vals['nb_count'], vals['not_booked'] = self._not_booked(agent, wizard.date_to)
            if any(abs(vals[k]) > 0.005 for k in ('opening', 'earned', 'paid', 'closing', 'not_booked')):
                rows.append(vals)
        totals = {k: sum(r[k] for r in rows) for k in ('opening', 'earned', 'paid', 'closing', 'unbilled',
                                                        'billed', 'not_booked')}
        return {'company': self.env.company, 'date_from': wizard.date_from, 'date_to': wizard.date_to,
                'rows': rows, 'totals': totals}


class AgentSummaryReport(models.AbstractModel):
    _name = "report.combine_commission.agent_summary_document"
    _inherit = "report.combine_commission.agent_ledger_document"
    _description = "Agent Outstanding Summary"


class CommissionBillReport(models.AbstractModel):
    _name = "report.combine_commission.report_commission_bill"
    _description = "Commission Bill"

    def _get_report_values(self, docids, data=None):
        return {"docs": self.env["account.move"].browse(docids),
                **self.env["partner_ledger_qty.voucher.mixin"]._helpers()}
