import logging

from odoo import _, models

from odoo.addons.odoo_master_child.models.rpc_client import ChildUnreachable

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = 'res.company'

    def _mcs_sync_one(self, rec, rpc=None):
        """Same as Master-Child Sync's own, except that the background sync
        creates missing master data by itself and a failure keeps its real
        reason on the record."""
        try:
            rec.with_context(mcs_auto_create=True)._sync_to_child(from_button=True, rpc=rpc)
            self.env.cr.commit()
            return rec.x_child_sync_state
        except ChildUnreachable:
            self.env.cr.rollback()
            raise
        except Exception as e:
            self.env.cr.rollback()
            _logger.exception('MCS bulk sync: failed on %s #%s', rec._name, rec.id)
            try:
                rec.write({'x_child_sync_state': 'error',
                           'x_child_sync_message': _('Sync failed: %s', e)})
                self.env.cr.commit()
            except Exception:
                self.env.cr.rollback()
            return 'error'
