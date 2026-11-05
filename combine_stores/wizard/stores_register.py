from odoo import _, fields, models

DOC_TYPES = [
    ('igp', 'Gate Pass Inward (IGP)'),
    ('inspection', 'Quality Inspection'),
    ('grn', 'Goods Receipt Note (GRN)'),
    ('ogp', 'Gate Pass Outward (OGP)'),
    ('delivery', 'Delivery Challan'),
    ('issue', 'Material Issue to Production'),
]


class StoresRegisterWizard(models.TransientModel):
    """Document-wise register for every stores document: one block per
    document (number, party, date, references, status) with its items, then
    the next document. Filters: period, parties, party types, items, item
    categories, status (and department for material issues)."""
    _name = 'combine.stores.register.wizard'
    _inherit = 'combine.register.mixin'
    _description = 'Stores Registers'
    _register_report_xmlid = 'combine_stores.action_report_stores_register'

    doc_type = fields.Selection(DOC_TYPES, string='Register', required=True, default='grn')
    status = fields.Selection([('done', 'Completed only'), ('all', 'All, including draft')], required=True, default='done')
    department_ids = fields.Many2many('combine.production.department', 'combine_stores_reg_dept_rel', 'wizard_id', 'department_id', string='Departments',
                                      help='Material issues only. Leave empty for all.')

    # ---------------------------------------------------------------- helpers
    def _dt_domain(self, field):
        start = fields.Datetime.to_datetime(self.date_from)
        end = fields.Datetime.add(fields.Datetime.to_datetime(self.date_to), days=1)
        return [(field, '>=', start), (field, '<', end)]

    def _d_domain(self, field):
        return [(field, '>=', self.date_from), (field, '<=', self.date_to)]

    @staticmethod
    def _state_label(rec):
        return dict(rec._fields['state']._description_selection(rec.env)).get(rec.state, rec.state)

    def _block(self, doc, sub_parts, rows, total_cols):
        totals = {c: sum(r[c] for r in rows if isinstance(r[c], (int, float))) for c in total_cols}
        return {'title': doc.name, 'sub': ' | '.join(p for p in sub_parts if p), 'rows': rows, 'totals': totals}

    # ---------------------------------------------------------------- data
    def _register_data(self):
        self.ensure_one()
        builder = getattr(self, '_data_' + self.doc_type)
        columns, groups, total_cols = builder()
        grand = {c: sum(g['totals'].get(c, 0.0) for g in groups) for c in total_cols} if groups else {}
        filters = self._register_filter_lines()
        if self.doc_type == 'issue' and self.department_ids:
            filters.append((_('Departments'), ', '.join(self.department_ids.mapped('name'))))
        filters.append((_('Status'), dict(self._fields['status'].selection)[self.status]))
        title = dict(DOC_TYPES)[self.doc_type] + ' ' + _('Register')
        return {'title': title, 'filters': filters, 'columns': columns, 'groups': groups, 'totals': grand}

    def _data_igp(self):
        dom = self._dt_domain('date') + [('state', '!=', 'cancel')]
        if self.status == 'done':
            dom.append(('state', 'in', ('in', 'inspected', 'done')))
        columns = [(_('Item'), 't'), (_('Qty as per Party'), 'q'), (_('Qty at Gate'), 'q'), (_('UoM'), 'c'),
                   (_('Packages'), 'q'), (_('Gross Wt.'), 'q'), (_('Tare Wt.'), 'q'), (_('Net Wt.'), 'q'), (_('Remarks'), 't')]
        groups = []
        for gp in self.env['combine.gate.pass.in'].search(dom, order='date, id'):
            if not self._register_partner_ok(gp.partner_id):
                continue
            rows = [[l.product_id.display_name, l.qty_doc, l.qty_received, l.uom_id.name, float(l.packages),
                     l.gross_weight, l.tare_weight, l.net_weight, l.note or '']
                    for l in gp.line_ids if self._register_product_ok(l.product_id)]
            if rows:
                groups.append(self._block(gp, [gp.partner_id.commercial_partner_id.name, fields.Datetime.to_string(gp.date)[:16],
                                               gp.purchase_id.name, gp.party_ref and _('Party ref: %s', gp.party_ref),
                                               gp.vehicle_no and _('Vehicle: %s', gp.vehicle_no), self._state_label(gp)],
                                          rows, (1, 2, 4, 5, 6, 7)))
        return columns, groups, (1, 2, 4, 5, 6, 7)

    def _data_inspection(self):
        dom = self._d_domain('date') + [('state', '!=', 'cancel')]
        if self.status == 'done':
            dom.append(('state', '=', 'done'))
        columns = [(_('Item'), 't'), (_('Received'), 'q'), (_('Accepted'), 'q'), (_('Rejected'), 'q'), (_('UoM'), 'c'),
                   (_('Reason / Remarks'), 't')]
        groups = []
        for ins in self.env['combine.inspection'].search(dom, order='date, id'):
            if not self._register_partner_ok(ins.partner_id):
                continue
            rows = [[l.product_id.display_name, l.qty_received, l.qty_accepted, l.qty_rejected, l.uom_id.name, l.reason or '']
                    for l in ins.line_ids if self._register_product_ok(l.product_id)]
            if rows:
                groups.append(self._block(ins, [ins.partner_id.commercial_partner_id.name, fields.Date.to_string(ins.date),
                                                ins.gate_pass_id.name, ins.purchase_id.name, self._state_label(ins)],
                                          rows, (1, 2, 3)))
        return columns, groups, (1, 2, 3)

    def _data_grn(self):
        dom = self._d_domain('date') + [('state', '!=', 'cancel')]
        if self.status == 'done':
            dom.append(('state', '=', 'done'))
        columns = [(_('Item'), 't'), (_('Qty Received'), 'q'), (_('UoM'), 'c'), (_('Net Wt.'), 'q'),
                   (_('Purchase Order'), 'c'), (_('Remarks'), 't')]
        groups = []
        for grn in self.env['combine.grn'].search(dom, order='date, id'):
            if not self._register_partner_ok(grn.partner_id):
                continue
            rows = [[l.product_id.display_name, l.qty, l.uom_id.name, l.net_weight,
                     l.purchase_line_id.order_id.name or '-', l.note or '']
                    for l in grn.line_ids if self._register_product_ok(l.product_id)]
            if rows:
                groups.append(self._block(grn, [grn.partner_id.commercial_partner_id.name, fields.Date.to_string(grn.date),
                                                grn.gate_pass_id.name, grn.gate_pass_id.party_ref and _('Party ref: %s', grn.gate_pass_id.party_ref),
                                                ', '.join(grn.picking_ids.mapped('name')), self._state_label(grn)],
                                          rows, (1, 3)))
        return columns, groups, (1, 3)

    def _data_ogp(self):
        dom = self._dt_domain('date') + [('state', '!=', 'cancel')]
        if self.status == 'done':
            dom.append(('state', '=', 'out'))
        columns = [(_('Item'), 't'), (_('Quantity'), 'q'), (_('UoM'), 'c'), (_('Packages'), 'q'), (_('Gross Wt.'), 'q'),
                   (_('Tare Wt.'), 'q'), (_('Net Wt.'), 'q'), (_('Remarks'), 't')]
        types = dict(self.env['combine.gate.pass.out']._fields['pass_type'].selection)
        groups = []
        for gp in self.env['combine.gate.pass.out'].search(dom, order='date, id'):
            if not self._register_partner_ok(gp.partner_id):
                continue
            rows = [[l.product_id.display_name, l.qty, l.uom_id.name, float(l.packages), l.gross_weight, l.tare_weight,
                     l.net_weight, l.note or ''] for l in gp.line_ids if self._register_product_ok(l.product_id)]
            if rows:
                groups.append(self._block(gp, [gp.partner_id.commercial_partner_id.name, fields.Datetime.to_string(gp.date)[:16],
                                               types.get(gp.pass_type), gp.picking_id.name, gp.invoice_ref and _('Invoice: %s', gp.invoice_ref),
                                               gp.vehicle_no and _('Vehicle: %s', gp.vehicle_no), self._state_label(gp)],
                                          rows, (1, 3, 4, 5, 6)))
        return columns, groups, (1, 3, 4, 5, 6)

    def _data_delivery(self):
        dom = [('picking_type_code', '=', 'outgoing'), ('company_id', '=', self.env.company.id)]
        if self.status == 'done':
            dom += [('state', '=', 'done')] + self._dt_domain('date_done')
        else:
            dom += [('state', '!=', 'cancel')] + self._dt_domain('scheduled_date')
        columns = [(_('Item'), 't'), (_('Ordered'), 'q'), (_('Delivered'), 'q'), (_('UoM'), 'c'), (_('Weight'), 'q')]
        groups = []
        for pick in self.env['stock.picking'].search(dom, order='date_done, scheduled_date, id'):
            if pick.partner_id and not self._register_partner_ok(pick.partner_id):
                continue
            if not pick.partner_id and (self.partner_ids or self.party_type_ids):
                continue
            rows = []
            for m in pick.move_ids.filtered(lambda m: m.state != 'cancel'):
                if not self._register_product_ok(m.product_id):
                    continue
                weight = (m.product_id.weight or 0.0) * m.product_uom._compute_quantity(m.quantity, m.product_id.uom_id)
                rows.append([m.product_id.display_name, m.product_uom_qty, m.quantity, m.product_uom.name, weight])
            if rows:
                passes = pick.x_gate_pass_out_ids.mapped('name') if 'x_gate_pass_out_ids' in pick._fields else []
                when = pick.date_done or pick.scheduled_date
                groups.append(self._block(pick, [pick.partner_id.commercial_partner_id.name, fields.Datetime.to_string(when)[:10],
                                                 pick.sale_id.name if 'sale_id' in pick._fields else pick.origin,
                                                 passes and _('OGP: %s', ', '.join(passes)), self._state_label(pick)],
                                          rows, (1, 2, 4)))
        return columns, groups, (1, 2, 4)

    def _data_issue(self):
        dom = self._d_domain('date') + [('state', '!=', 'cancel')]
        if self.status == 'done':
            dom.append(('state', '=', 'done'))
        if self.department_ids:
            dom.append(('department_id', 'in', self.department_ids.ids))
        columns = [(_('Item'), 't'), (_('Quantity'), 'q'), (_('UoM'), 'c'), (_('Cost / Unit'), 'n'), (_('Value'), 'n'), (_('Remarks'), 't')]
        groups = []
        for issue in self.env['combine.material.issue'].search(dom, order='date, id'):
            rows = [[l.product_id.display_name, l.qty, l.uom_id.name, l.unit_cost, l.value, l.note or '']
                    for l in issue.line_ids if self._register_product_ok(l.product_id)]
            if rows:
                groups.append(self._block(issue, [issue.department_id.name, fields.Date.to_string(issue.date),
                                                  issue.location_id.display_name, issue.requested_by and _('Requested by %s', issue.requested_by),
                                                  self._state_label(issue)], rows, (1, 4)))
        return columns, groups, (1, 4)
