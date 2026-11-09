from odoo import _, api, models


class YapieWorkflow(models.AbstractModel):
    _inherit = 'yapie.workflow'

    @api.model
    def _yapie_workflows(self):
        """combine001's approval workflows - groups and buttons exactly as combine001 enforces them."""
        out = super()._yapie_workflows()
        env = self.env
        if 'x_approval_state' in env['stock.picking']._fields:
            out.append({
                'key': 'combine001.purchase_receipt', 'name': _('Purchase Receipt approval (combine001)'), 'model': 'stock.picking',
                'domain': [('picking_type_code', '=', 'incoming'), ('purchase_id', '!=', False), ('x_approval_state', '=', 'submitted')],
                'groups': ['purchase.group_purchase_manager'], 'mode': 'any',
                'approve': 'action_combine001_approve', 'reject': 'action_combine001_reject', 'reason_field': 'x_rejection_reason',
            })
        if 'x_approval_state' in env['account.move']._fields:
            out.append({
                'key': 'combine001.vendor_bill', 'name': _('Vendor Bill / Debit Note approval (combine001)'), 'model': 'account.move',
                'domain': [('move_type', 'in', ('in_invoice', 'in_refund')), ('x_approval_state', '=', 'submitted')],
                'groups': ['account.group_account_manager'], 'mode': 'any',
                'approve': 'action_combine001_approve', 'reject': 'action_combine001_reject', 'reason_field': 'x_rejection_reason',
            })
        if 'x_price_approval_state' in env['sale.order']._fields:
            out.append({
                'key': 'combine001.contract_price', 'name': _('Contract price change approval (combine001)'), 'model': 'sale.order',
                'domain': [('x_price_approval_state', '=', 'pending')],
                'groups': ['sales_team.group_sale_manager'], 'mode': 'any',
                'approve': 'action_combine001_approve_price', 'reject': 'action_combine001_reject_price',
            })
        for model, key, name, group in (
                ('combine001.sale.amendment', 'combine001.sale_amendment', _('Contract Amendment approval (combine001)'), 'sales_team.group_sale_manager'),
                ('combine001.purchase.amendment', 'combine001.purchase_amendment', _('Purchase Order Amendment approval (combine001)'), 'purchase.group_purchase_manager'),
                ('combine001.tax.adjustment', 'combine001.tax_adjustment', _('Tax Adjustment approval (combine001)'), 'account.group_account_manager')):
            if model in env:
                out.append({'key': key, 'name': name, 'model': model, 'domain': [('state', '=', 'pending')], 'groups': [group], 'mode': 'any',
                            'approve': 'action_approve', 'reject': 'action_reject'})
        return out
