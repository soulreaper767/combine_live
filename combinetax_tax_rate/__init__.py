from . import models

# document table, line table, line -> document column, tax relation table, relation's line column, which lines count
_TABLES = [
    ('sale_order', 'sale_order_line', 'order_id', 'account_tax_sale_order_line_rel', 'sale_order_line_id',
     'l.display_type IS NULL'),
    ('purchase_order', 'purchase_order_line', 'order_id', 'account_tax_purchase_order_line_rel', 'purchase_order_line_id',
     'l.display_type IS NULL'),
    ('account_move', 'account_move_line', 'move_id', 'account_move_line_account_tax_rel', 'account_move_line_id',
     "l.display_type = 'product'"),
]


def pre_init_hook(env):
    """Create and fill the two new columns directly, before the module
    loads: Odoo only recomputes a new stored field when it has to create
    the column itself, so existing orders, invoices and bills are not
    written to (their 'last updated' stays as it is). Same result as
    the Python compute in models/tax_rate.py."""
    cr = env.cr
    for doc, line, fk, rel, rel_line, cond in _TABLES:
        cr.execute(f"ALTER TABLE {doc} ADD COLUMN IF NOT EXISTS x_tax_rate numeric, "
                   f"ADD COLUMN IF NOT EXISTS x_tax_rates varchar")
        cr.execute(f"""
            WITH line_rate AS (
                SELECT l.{fk} AS doc_id, l.id AS line_id,
                       COALESCE(SUM(t.amount) FILTER (WHERE t.amount_type = 'percent'), 0) AS rate
                  FROM {line} l
             LEFT JOIN {rel} r ON r.{rel_line} = l.id
             LEFT JOIN account_tax t ON t.id = r.account_tax_id
                 WHERE {cond}
              GROUP BY l.{fk}, l.id
            ), rates AS (
                SELECT doc_id, string_agg(label, ', ' ORDER BY amount) AS labels
                  FROM (SELECT DISTINCT l.{fk} AS doc_id, t.amount, trim_scale(t.amount)::text || '%' AS label
                          FROM {line} l
                          JOIN {rel} r ON r.{rel_line} = l.id
                          JOIN account_tax t ON t.id = r.account_tax_id AND t.amount_type = 'percent'
                         WHERE {cond}) d
              GROUP BY doc_id
            )
            UPDATE {doc} d
               SET x_tax_rate = COALESCE((SELECT MAX(rate) FROM line_rate WHERE line_rate.doc_id = d.id), 0),
                   x_tax_rates = (SELECT labels FROM rates WHERE rates.doc_id = d.id)
        """)
