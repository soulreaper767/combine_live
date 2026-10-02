"""Shared constants referenced by more than one model file.

Kept in one place so the account codes used to *create* the GST Saving
accounts (models/res_company.py) and the codes used to *look them up*
when posting an invoice/bill (models/account_move.py) can never drift
apart.
"""

GST_SAVING_ASSET_CODE = '3.13.01.0001'
GST_SAVING_EQUITY_CODE = '1.09.01.0001'

# Withholding tax accounts. Purchase-side (tax WE withhold from a
# Vendor payment) reuses an EXISTING leaf account from the real imported
# CoA - "TAX AT SOURCE - PARTIES" under the CoA's own "TAX AT SOURCE"
# liability group is exactly this. Sale-side (tax a Customer withholds
# from paying US - an asset, recoverable against our own final tax
# liability) has no existing leaf account, only the matching empty group
# "ADVANCE INCOME TAX AGAINST LOCAL SUPPLIES" - a new leaf is created
# under it (see _STRUCTURAL_ACCOUNTS in res_company.py). See README.md
# for the full reasoning.
WHT_PURCHASE_PAYABLE_CODE = '2.12.01.0001'   # TAX AT SOURCE - PARTIES (existing)
WHT_SALE_RECEIVABLE_CODE = '3.11.03.0001'    # ADVANCE INCOME TAX AGAINST LOCAL SUPPLIES (new leaf)
