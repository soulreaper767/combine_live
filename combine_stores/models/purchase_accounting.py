"""Automatic ledger entries along the purchase / stores flow (perpetual).

  GRN (receipt from vendor)     Dr Stock (category)        Cr GRN Clearing
  Vendor bill                   Dr GRN Clearing + GST      Cr Creditors
  Return to vendor              Dr GRN Clearing            Cr Stock
  Issue to production           Dr Consumption (category)  Cr Stock
  Back from production          Dr Stock                   Cr Consumption

Applies to items whose category is "Perpetual"; only to documents done
from now on - receipts done earlier made no entry and their bills post as
Odoo does (to the stock account), so nothing existing changes.
"""
from odoo import _, api, models

GRN_CLEARING_CODE = '2.07.14'


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _compute_reference(self):
        super()._compute_reference()
        # moves without a transfer (material issues, production batches): their document number
        for move in self:
            if not move.reference and move.origin and not move.picking_id:
                move.reference = move.origin

    def _set_value(self, correction_quantity=None):
        res = super()._set_value(correction_quantity=correction_quantity)
        # goods returned to the vendor leave at the price they came in at, so the
        # debit note clears GRN Clearing exactly (not at today's average cost)
        for move in self:
            origin = move.origin_returned_move_id
            if (not correction_quantity and origin and origin.state == 'done' and origin.purchase_line_id
                    and move.location_dest_id.usage == 'supplier' and move.product_id.valuation == 'real_time'):
                origin_qty = origin.product_uom._compute_quantity(origin.quantity, origin.product_id.uom_id)
                qty = move.product_uom._compute_quantity(move.quantity, move.product_id.uom_id)
                if origin_qty and origin.value:
                    move.value = origin.value / origin_qty * qty
        return res

    def _combine_production_side(self):
        """'in' / 'out' when the move goes into / comes out of a production (department) location."""
        if self.location_dest_id.usage == 'production' and self.location_id.usage == 'internal':
            return 'in'
        if self.location_id.usage == 'production' and self.location_dest_id.usage == 'internal':
            return 'out'
        return None

    def _should_create_account_move(self):
        res = super()._should_create_account_move()
        if res:
            return res
        self.ensure_one()
        return bool(self._combine_production_side() and self.product_id.is_storable and self.is_valued
                    and self.product_id.valuation == 'real_time'
                    and not self.product_uom.is_zero(self.quantity)
                    and self.product_id.product_tmpl_id.get_product_accounts()['expense'])

    def _get_account_move_line_vals(self):
        side = self._combine_production_side()
        if not side or self.location_id.valuation_account_id or self.location_dest_id.valuation_account_id:
            return super()._get_account_move_line_vals()
        accounts = self.product_id.product_tmpl_id.get_product_accounts()
        stock, consumption = accounts['stock_valuation'], accounts['expense']
        debit, credit = (consumption, stock) if side == 'in' else (stock, consumption)
        value = self._get_aml_value()
        name = (self.reference or self.origin or '') + ' - ' + self.product_id.name
        return [{'account_id': credit.id, 'name': name, 'debit': 0, 'credit': value, 'product_id': self.product_id.id},
                {'account_id': debit.id, 'name': name, 'debit': value, 'credit': 0, 'product_id': self.product_id.id}]


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    def _compute_account_id(self):
        super()._compute_account_id()
        clearing = self.env['stock.location'].sudo().search([('usage', '=', 'supplier'), ('valuation_account_id', '!=', False)],
                                                             limit=1).valuation_account_id
        if not clearing:
            return
        for line in self:
            if not line.move_id.is_purchase_document() or not line.purchase_line_id or not line._eligible_for_stock_account():
                continue
            if line.product_id.valuation != 'real_time':
                continue
            # the goods were received with a GRN entry (stock vs clearing): the bill clears it
            moves = line.purchase_line_id.move_ids.filtered(lambda m: m.state == 'done')
            if moves and any(m.account_move_id for m in moves):
                line.account_id = clearing


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def _update_standard_price(self, extra_value=None, extra_quantity=None):
        # switching a category's cost method must not re-cost what is already in stock
        if self.env.context.get('combine_keep_current_cost'):
            return
        return super()._update_standard_price(extra_value=extra_value, extra_quantity=extra_quantity)


class StockLocation(models.Model):
    _inherit = 'stock.location'

    @api.model
    def _combine_setup_purchase_accounting(self):
        """One-time setup: adds what is missing, fills only empty settings."""
        env = self.env
        company = env.company
        Account = env['account.account'].with_company(company)
        log = []

        def account(code, name, atype, reconcile=False):
            acc = Account.search([('code', '=', code)], limit=1)
            if not acc:
                acc = Account.create({'code': code, 'name': name, 'account_type': atype, 'reconcile': reconcile})
                log.append('account created %s %s' % (code, name))
            return acc

        clearing = account(GRN_CLEARING_CODE, 'GOODS RECEIVED NOT BILLED (GRN CLEARING)', 'liability_current', reconcile=True)
        stores_stock = account('3.08.04.0001', 'STORES, SPARES & LOOSE TOOLS STOCK', 'asset_current')
        store_consumed = Account.search([('code', '=', '5.03.01.0001')], limit=1)

        if not company.account_stock_journal_id:
            journal = env['account.journal'].search([('type', '=', 'general'), ('company_id', '=', company.id)], limit=1)
            if journal:
                company.account_stock_journal_id = journal
                log.append('stock journal -> %s' % journal.name)

        vendors = env.ref('stock.stock_location_suppliers', raise_if_not_found=False)
        if vendors and not vendors.valuation_account_id:
            vendors.valuation_account_id = clearing
            log.append('Vendors location -> GRN clearing')

        Categ = env['product.category'].with_company(company)
        stores = Categ.search([('name', '=', 'Stores')], limit=1)
        if stores:
            if not stores.property_stock_valuation_account_id:
                stores.property_stock_valuation_account_id = stores_stock
                log.append('Stores stock account')
            if not stores.property_account_expense_categ_id and store_consumed:
                stores.property_account_expense_categ_id = store_consumed
                log.append('Stores consumption account')
        # raw material + stores: perpetual, average cost - keeping every item's current cost
        targets = Categ.search([('property_stock_valuation_account_id', '!=', False),
                                ('property_stock_valuation_account_id.code', '=like', '3.08.0_.%')]).filtered(
            lambda c: not c.property_stock_valuation_account_id.code.startswith('3.08.01'))  # finished goods stay as they are
        todo = targets.filtered(lambda c: c.property_valuation != 'real_time' or c.property_cost_method != 'average')
        if todo:
            todo.with_context(combine_keep_current_cost=True).write({'property_valuation': 'real_time', 'property_cost_method': 'average'})
            log.append('perpetual + average: %s' % ', '.join(todo.mapped('name')))
        return log
