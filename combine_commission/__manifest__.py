{
    'name': 'Combine - Commission',
    'version': '19.0.1.1.0',
    'category': 'Accounting',
    'summary': 'Commission agents as parties: commission booked in the accounts, commission bills, '
               'payments, and the Commission Agent Ledger',
    'description': """
Combine - Commission
====================
Builds on combine001's commission lines (one per sales invoice line of a
contract with a commission agent).

1. Booking: when a sales invoice is posted (from the invoice or from the
   list), its commission is booked at once:
       Dr 6.02.05.0001 Commission on Yarn Sales
       Cr 2.13.02.0003 Unbilled Invoices (Commission)   - partner: the agent
   A credit note books the reverse; an invoice reset to draft (or a
   revised contract) reverses what it booked.
2. Commission bill: "Bill Commission" on a posted sales invoice, or
   Commission Settlement (agent + period, pick the lines), creates the
   agent's vendor bill:
       Dr 2.13.02.0003 Unbilled Invoices (Commission)
       Cr 2.07.15 Trade Creditors - Control              - partner: the agent
   It goes through the normal vendor-bill approval (Finance Manager).
3. Payment: the normal BPV / CPV voucher against the agent's bill;
   withholding tax per the Withholding Tax Rates table (shown on the bill).
   Commission lines follow: Not booked > Unbilled > Billed > Paid.
5. Pending Contracts (Sales > Reporting): contract-wise or party-wise, per
   contract, item or delivery challan - quantity, rate, value, GST, commission,
   delivered, pending delivery, invoiced, delivered-not-invoiced, pending values.
4. Commission Agent Ledger (PDF / Excel, house style, same layout as the
   Partner Ledger Print) and Agent Outstanding Summary.

Existing data is never changed: installing books nothing, edits no agent,
company or commission line. Commission of invoices posted before
installation stays "Not booked" until someone deliberately books it with
"Book Commission" (Finance Manager).
""",
    'author': 'Sibyl Technologies',
    'license': 'LGPL-3',
    'depends': ['combine001', 'partner_ledger_qty'],
    'data': [
        'security/ir.model.access.csv',
        'data/party_type_data.xml',
        'report/agent_ledger_report.xml',
        'report/commission_bill_report.xml',
        'wizard/agent_ledger_wizard_views.xml',
        'wizard/commission_wizard_views.xml',
        'wizard/pending_contracts_views.xml',
        'views/commission_views.xml',
    ],
    'installable': True,
    'application': False,
}
