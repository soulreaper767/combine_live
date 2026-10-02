from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StockPickingType(models.Model):
    """The PDF report title ('Delivery Note' -> 'Delivery Challan') is
    driven by this method, not a static template string - overriding it
    here also fixes the report automatically. The picking type's own
    `name` field (drives the Inventory app's operation-type cards/menus)
    is renamed separately, per-warehouse, in
    res_company._combine001_rename_delivery_picking_types - it's real
    data (one record per warehouse), not a fixed view/action to inherit."""
    _inherit = 'stock.picking.type'

    def _get_code_report_name(self):
        self.ensure_one()
        if self.code == 'outgoing':
            return _('Delivery Challan')
        return super()._get_code_report_name()


class StockPicking(models.Model):
    """BRD sec. 7: the existing Delivery Note functionality is retained
    technically (this module does not touch stock.picking's own workflow
    or its stock-deduction-on-validate behaviour at all) - only its
    business-facing name changes to 'Delivery Challan' (see
    views/stock_picking_delivery_challan_views.xml for the cosmetic
    relabeling, same technique as the Quotation -> Contract rename), and
    it gains the registration-status fields the BRD wants visible on it.
    Raised directly from the confirmed Delivery Order (sale.order) via
    Odoo's own native procurement - there is no separate Delivery Out
    step in between (removed per the Change Request Document for Sales
    Module, 2026-09-28).
    """
    _name = 'stock.picking'
    _inherit = ['stock.picking', 'combine001.tax.status.mixin', 'combine001.approval.mixin']

    x_show_pra_status = fields.Boolean(compute='_compute_x_show_pra_status')
    x_gate_pass_id = fields.Many2one('combine001.gate.pass', compute='_compute_x_gate_pass_id', string='Gate Pass')

    @api.depends('move_ids.product_id.x_pra_applicable')
    def _compute_x_show_pra_status(self):
        for picking in self:
            picking.x_show_pra_status = bool(picking.move_ids.product_id.filtered('x_pra_applicable'))

    def _combine001_approval_group(self):
        return 'purchase.group_purchase_manager'

    def button_validate(self):
        """BRD for Purchase Module Changes sec. 7: Purchase Receipt
        workflow (Draft -> Submitted -> Approved -> Done) - only
        enforced for an incoming transfer actually linked to a Purchase
        Order; every other transfer (Delivery Challan, internal moves,
        a receipt not tied to a purchase) is completely unaffected."""
        purchase_receipts = self.filtered(
            lambda p: p.picking_type_code == 'incoming' and p.purchase_id)
        purchase_receipts._combine001_check_approved(_('validated'))
        return super().button_validate()

    def _compute_x_gate_pass_id(self):
        gate_passes = self.env['combine001.gate.pass'].search([('picking_id', 'in', self.ids)])
        by_picking = {gp.picking_id.id: gp for gp in gate_passes}
        for picking in self:
            picking.x_gate_pass_id = by_picking.get(picking.id, False)

    def action_combine001_create_gate_pass(self):
        """BRD sec. 8: Gate Pass is generated from the validated Delivery
        Challan; no additional stock deduction happens here - this only
        creates the reference document, stock already moved when this
        picking was validated."""
        self.ensure_one()
        if self.picking_type_code != 'outgoing':
            raise UserError(_('A Gate Pass can only be created for an outgoing Delivery Challan.'))
        if self.state != 'done':
            raise UserError(_('The Delivery Challan must be validated before a Gate Pass can be created.'))
        if self.x_gate_pass_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'combine001.gate.pass',
                'view_mode': 'form',
                'res_id': self.x_gate_pass_id.id,
            }
        gate_pass = self.env['combine001.gate.pass'].create({'picking_id': self.id})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'combine001.gate.pass',
            'view_mode': 'form',
            'res_id': gate_pass.id,
        }
