from odoo import api, fields, models

GST = [('registered', 'Registered'), ('unregistered', 'Unregistered')]
ITAX = [('filer', 'Filer'), ('non_filer', 'Non-Filer')]
STATUS_FIELDS = ('x_gst_status', 'x_income_tax_status', 'x_pra_status')


class TaxStatusMixin(models.AbstractModel):
    """combine001 kept these as stored fields RELATED to the party, so any change of the party's
    status rewrote every document of that party (and, through the GST swap, the taxes of
    confirmed contracts and posted invoices). Here they become plain stored fields - the column and
    every value already in it stay exactly as they are - stamped from the status in force on the
    document's own date when it is created, and while it is still open (draft) when its date or
    party changes."""
    _inherit = 'combine001.tax.status.mixin'

    x_gst_status = fields.Selection(GST, related=False, readonly=True, copy=False, string='GST Status')
    x_income_tax_status = fields.Selection(ITAX, related=False, readonly=True, copy=False, string='Income Tax Status')
    x_pra_status = fields.Selection(GST, related=False, readonly=True, copy=False, string='PRA Status')

    _combine_status_triggers = ('partner_id',)

    def _combine_status_date(self):
        self.ensure_one()
        return fields.Date.context_today(self)

    def _combine_status_open(self):
        return True

    def _combine_status_tax_lines(self):
        """Lines whose taxes follow the GST status: {line: keep_as_is}. Empty for documents without taxes."""
        return {}

    def _combine_stamp_status(self, on_date=None):
        Period = self.env['combine.tax.status.period']
        for rec in self:
            vals = Period._combine_statuses_at(rec.partner_id, on_date or rec._combine_status_date(),
                                               rec.company_id if 'company_id' in rec._fields else None)
            vals = {k: v for k, v in vals.items() if rec[k] != v}
            if not vals:
                continue
            # the taxes the lines have now (from the contract, typed in, or the product) stay; a status
            # change only swaps the GST rate 18 <-> 22. Without this, Odoo would recompute the lines'
            # taxes from the product defaults and drop taxes carried from the contract.
            lines = rec._combine_status_tax_lines()
            snapshot = {line: line.tax_ids for line in lines}
            rec.with_context(combine_status_stamp=True).write(vals)
            for line, keep in lines.items():
                taxes = snapshot[line]
                if not keep:
                    taxes = taxes._combine_gst_for_status(rec.x_gst_status, rec.company_id)
                if line.tax_ids != taxes:
                    line.tax_ids = taxes

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._combine_stamp_status()
        return records

    def write(self, vals):
        if self.env.context.get('combine_status_stamp') or not any(k in vals for k in self._combine_status_triggers):
            return super().write(vals)
        open_before = self.filtered(lambda r: r._combine_status_open())
        res = super().write(vals)
        # re-stamped when it WAS still open before this write - e.g. a quotation confirmed now takes the
        # status of its confirmation date; once confirmed / posted / done it never changes again
        open_before._combine_stamp_status()
        return res


class SaleOrder(models.Model):
    _inherit = 'sale.order'
    _combine_status_triggers = ('partner_id', 'date_order')

    def _combine_status_date(self):
        self.ensure_one()
        return fields.Date.context_today(self, self.date_order) if self.date_order else fields.Date.context_today(self)

    def _combine_status_open(self):
        return self.state in ('draft', 'sent')

    def _combine_status_tax_lines(self):
        if self.state not in ('draft', 'sent'):
            return {}
        return {line: False for line in self.order_line if line.product_id and not line.display_type}

    def action_confirm(self):
        # Odoo dates a contract on its confirmation: apply that day's status while it is still a quotation,
        # so its GST rate (18 / 22) follows it; lines without GST stay without GST
        for order in self.filtered(lambda o: o.state in ('draft', 'sent')):
            order._combine_stamp_status(on_date=fields.Date.context_today(order))
        return super().action_confirm()


class AccountMove(models.Model):
    _inherit = 'account.move'
    _combine_status_triggers = ('partner_id', 'invoice_date', 'date')

    def _combine_status_date(self):
        self.ensure_one()
        return self.invoice_date or self.date or fields.Date.context_today(self)

    def _combine_status_open(self):
        return self.state == 'draft'

    def _combine_status_tax_lines(self):
        if self.state != 'draft' or not self.is_invoice(include_receipts=True):
            return {}
        # lines raised from a contract keep the contract's taxes exactly; other sale lines follow the status
        return {line: bool(line.sale_line_ids) or not self.is_sale_document(include_receipts=True)
                for line in self.invoice_line_ids if line.display_type == 'product'}


class StockPicking(models.Model):
    _inherit = 'stock.picking'
    _combine_status_triggers = ('partner_id', 'scheduled_date', 'date_done')

    def _combine_status_date(self):
        self.ensure_one()
        when = self.date_done or self.scheduled_date
        return fields.Date.context_today(self, when) if when else fields.Date.context_today(self)

    def _combine_status_open(self):
        return self.state not in ('done', 'cancel')


class GatePass(models.Model):
    _inherit = 'combine001.gate.pass'

    x_gst_status = fields.Selection(GST, related=False, readonly=True, copy=False, string='GST Status')
    x_income_tax_status = fields.Selection(ITAX, related=False, readonly=True, copy=False, string='Income Tax Status')
    x_pra_status = fields.Selection(GST, related=False, readonly=True, copy=False, string='PRA Status')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:   # same status as its delivery challan (stamped for the delivery date)
            rec.write({f: rec.picking_id[f] for f in STATUS_FIELDS})
        return records


# ---------------------------------------------------------------- GST 18 / 22 swap
class AccountTax(models.Model):
    _inherit = 'account.tax'

    def _combine_gst_for_status(self, status, company):
        """Swap a Combine001 sale GST tax for the rate of this status (18% registered, 22% unregistered)."""
        gst_tax = self.filtered(lambda t: t.x_combine001_gst and t.type_tax_use == 'sale')
        if not gst_tax or not status:
            return self
        rate = 22.0 if status == 'unregistered' else 18.0
        if gst_tax[0].amount == rate:
            return self
        replacement = self.env['account.tax'].search([('company_id', '=', company.id), ('type_tax_use', '=', 'sale'),
                                                      ('amount', '=', rate), ('x_combine001_gst', '=', True)], limit=1)
        return (self - gst_tax) | replacement if replacement else self


def _frozen(lines, locked_states, state_of):
    """Taxes of lines on a confirmed / posted / cancelled document that existed before this transaction."""
    if not lines:
        return {}
    now = lines.env.cr.now()
    return {line.id: line.tax_ids for line in lines
            if isinstance(line.id, int) and state_of(line) in locked_states
            and line.create_date and line.create_date != now}


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    @api.depends('order_id.x_gst_status')
    def _compute_tax_ids(self):
        frozen = _frozen(self, ('sale', 'cancel'), lambda l: l.order_id.state)
        super()._compute_tax_ids()
        for line in self:
            if line.id in frozen:
                if line.tax_ids != frozen[line.id]:
                    line.tax_ids = frozen[line.id]
                continue
            new = line.tax_ids._combine_gst_for_status(line.order_id.x_gst_status, line.company_id)
            if new != line.tax_ids:
                line.tax_ids = new


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    @api.depends('move_id.x_gst_status')
    def _compute_tax_ids(self):
        frozen = _frozen(self, ('posted', 'cancel'), lambda l: l.move_id.state)
        super()._compute_tax_ids()
        for line in self:
            if line.id in frozen:
                if line.tax_ids != frozen[line.id]:
                    line.tax_ids = frozen[line.id]
                continue
            if line.move_id.is_sale_document(include_receipts=True):
                new = line.tax_ids._combine_gst_for_status(line.move_id.x_gst_status, line.move_id.company_id)
                if new != line.tax_ids:
                    line.tax_ids = new
