"""Append-only evidence snapshots; callers own the surrounding transaction."""
from datetime import datetime, timezone


def record(con, topup, event, actor, reason='', request_id=None):
    if not con.in_transaction: raise RuntimeError('History requires a transaction')
    row=con.execute('SELECT * FROM topup_requests WHERE id=?',(topup,)).fetchone()
    con.execute('INSERT OR IGNORE INTO topup_evidence_claims VALUES(?,?,?)',(row['receipt_hash'],topup,row['receipt']))
    claim=con.execute('SELECT topup_id FROM topup_evidence_claims WHERE receipt_hash=?',(row['receipt_hash'],)).fetchone()
    if claim[0]!=topup: raise ValueError('Chek boshqa so‘rovga tegishli')
    con.execute('INSERT INTO topup_history VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (topup,row['revision'],event,actor,reason,datetime.now(timezone.utc).isoformat(),row['amount_minor'],row['receipt_hash'],row['qr_version'],row['terms_version'],row['payer_reference'],row['paid_at'],row['status'],request_id))


def view(row):
    return {'revision':row['revision'],'event':row['event'],'reason':row['reason'],'created':row['created'],
            'amountMinor':row['amount_minor'],'currency':'UZS','qrVersion':row['qr_version'],
            'payerReference':row['payer_reference'],'paidAt':row['paid_at'],'status':row['status']}
