import logging

from odoo import _, models
from odoo.exceptions import UserError

from odoo.addons.master_child_sync.models.sync_mixin import _plain_domain

_logger = logging.getLogger(__name__)

WITH_ARCHIVED = {'active_test': False}
# reference records the Child can be given automatically when it lacks them
CREATABLE = ('res.country.state', 'account.journal', 'account.tax')


class ChildSyncMixin(models.AbstractModel):
    _inherit = 'child.sync.mixin'

    def _mcs_find_plain(self, rpc, record):
        """Child id of a reference record, archived ones included.
        None when the model has no matching rule."""
        dom = _plain_domain(record)
        if dom is None:
            return None
        found = rpc.execute(record._name, 'search', dom, limit=1, context=WITH_ARCHIVED)
        return found[0] if found else False

    def _mcs_plain(self, rpc, record, ctx=None):
        if not record:
            return False
        record.ensure_one()
        cid = self._mcs_find_plain(rpc, record)
        if cid:
            return cid
        if cid is False and record._name in CREATABLE:
            return self._mcs_create_plain(rpc, record, {} if ctx is None else ctx)
        return super()._mcs_plain(rpc, record)

    def _mcs_taxes(self, rpc, taxes):
        ids = []
        for tax in taxes:
            if tax.amount_type == 'group':
                ids += super()._mcs_taxes(rpc, tax)
            else:
                ids.append(self._mcs_plain(rpc, tax))
        return ids

    def _mcs_create_plain(self, rpc, record, ctx):
        model = record._name
        if model == 'res.country.state':
            vals = {'name': record.name, 'code': record.code,
                    'country_id': self._mcs_plain(rpc, record.country_id)}
        elif model == 'account.journal':
            vals = {'name': record.name, 'code': record.code, 'type': record.type}
            if record.default_account_id:
                vals['default_account_id'] = record.default_account_id._child_ensure(rpc, ctx)
            if record.currency_id:
                vals['currency_id'] = self._mcs_plain(rpc, record.currency_id)
        elif model == 'account.tax':
            vals = self._mcs_tax_values(rpc, record, ctx)
        else:
            raise UserError(_('Cannot create %s in the Child.', model))
        cid = rpc.create(model, vals)
        _logger.info('MCS extras: created %s "%s" in the child (id %s)', model, record.display_name, cid)
        return cid

    def _mcs_tax_values(self, rpc, tax, ctx):
        def lines(repartition):
            return [(0, 0, {
                'document_type': line.document_type,
                'repartition_type': line.repartition_type,
                'factor_percent': line.factor_percent,
                'account_id': line.account_id._child_ensure(rpc, ctx) if line.account_id else False,
            }) for line in repartition]
        vals = {
            'name': tax.name,
            'amount': tax.amount,
            'amount_type': tax.amount_type,
            'type_tax_use': tax.type_tax_use,
            'include_base_amount': tax.include_base_amount,
            'invoice_repartition_line_ids': lines(tax.invoice_repartition_line_ids),
            'refund_repartition_line_ids': lines(tax.refund_repartition_line_ids),
        }
        for optional in ('price_include_override', 'is_base_affected', 'invoice_label'):
            if optional in tax._fields and tax[optional]:
                vals[optional] = tax[optional]
        return vals

    def _child_scan(self, rpc, ctx, _chain=()):
        found = super()._child_scan(rpc, ctx, _chain)
        auto = self.env.context.get('mcs_auto_create')
        keep = []
        for item in found:
            if item['model'] in CREATABLE:
                continue                      # created on the fly when the document is pushed
            if auto and item['can_create']:
                continue                      # background sync creates these itself
            if not item['can_create']:
                rec = self.env[item['model']].browse(item['res_id'])
                if self._mcs_find_plain(rpc, rec):
                    continue                  # exists in the Child, only archived
            keep.append(item)
        return keep
