import logging
import re

from odoo import _, models
from odoo.exceptions import UserError

from .sync_mixin import WITH_ARCHIVED

_logger = logging.getLogger(__name__)


def _norm(text):
    return re.sub(r'[^A-Z0-9]', '', (text or '').upper())


class AccountAccount(models.Model):
    _inherit = 'account.account'

    def _mcs_child_accounts(self, rpc, domain):
        return rpc.execute('account.account', 'search_read', domain, fields=['code', 'name'], context=WITH_ARCHIVED)

    def _child_find_twin(self, rpc):
        """Same account in the Child = the linked one, or one with the same
        code AND the same name. A Child account that only shares the code
        is a different account and is left alone."""
        self.ensure_one()
        if self.x_child_id:
            linked = self._mcs_child_accounts(rpc, [('id', '=', self.x_child_id)])
            if linked and (linked[0]['code'] == self.code or _norm(linked[0]['name']) == _norm(self.name)):
                return self.x_child_id
        for row in self._mcs_child_accounts(rpc, [('code', '=', self.code)]):
            if _norm(row['name']) == _norm(self.name):
                return row['id']
        return False

    def _child_prepare_values(self, rpc, ctx):
        vals = super()._child_prepare_values(rpc, ctx)
        clash = [row for row in self._mcs_child_accounts(rpc, [('code', '=', self.code)])
                 if row['id'] != self.x_child_id and _norm(row['name']) != _norm(self.name)]
        if clash:
            current = self._mcs_child_accounts(rpc, [('id', '=', self.x_child_id)]) if self.x_child_id else []
            if current and current[0]['code'] != self.code:
                vals['code'] = current[0]['code']          # keep the code it was given before
            else:
                vals['code'] = self._mcs_next_free_code(rpc, self.code)
                _logger.info('MCS extras: account %s exists in the child as "%s"; using code %s',
                             self.code, clash[0]['name'], vals['code'])
        return vals

    def _mcs_next_free_code(self, rpc, code):
        match = re.match(r'^(.*?)(\d+)$', code or '')
        prefix, number, width = (match.group(1), int(match.group(2)), len(match.group(2))) if match else ((code or '') + '.', 0, 4)
        for n in range(number + 1, number + 10000):
            candidate = f'{prefix}{n:0{width}d}'
            if not rpc.execute('account.account', 'search_count', [('code', '=', candidate)], context=WITH_ARCHIVED):
                return candidate
        raise UserError(_('No free account code after %s in the Child.', code))
