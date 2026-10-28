"""Audited, read-only booking oversight. No generic status override or refund."""
import json
import re
from urllib.parse import parse_qs, urlparse
from datetime import datetime, timezone
import booking_engine as engine
import booking_index
import booking_care
import conversations


def audit(con, actor, action, identity):
    con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',
                (actor,action,identity,datetime.now(timezone.utc).isoformat()))


def owned(con, identity):
    row=con.execute('SELECT b.*,q.snapshot FROM bookings b JOIN booking_quotes q ON q.id=b.quote_id WHERE b.id=?',(identity,)).fetchone()
    if not row:raise engine.BookingError(404,'Buyurtma topilmadi')
    return row


def page(con, query):
    before,status,bucket,text=booking_index.options(query)
    con.create_function('booking_fold',1,booking_index.folded,deterministic=True)
    clauses=[];args=[]
    if before is not None:clauses.append('b.seq<?');args.append(before)
    if status!='all':clauses.append('b.status=?');args.append(status)
    if bucket!='all':
        clauses.append('b.status IN ('+','.join('?' for _ in booking_index.BUCKETS[bucket])+')')
        args.extend(booking_index.BUCKETS[bucket])
    if text:
        clauses.append("(instr(booking_fold(b.id),?)>0 OR instr(booking_fold(json_extract(q.snapshot,'$.customerName')),?)>0 OR instr(booking_fold(json_extract(q.snapshot,'$.sitterName')),?)>0)")
        args.extend([text]*3)
    rows=con.execute('SELECT b.*,q.snapshot FROM bookings b JOIN booking_quotes q ON q.id=b.quote_id'+
                     (' WHERE '+' AND '.join(clauses) if clauses else '')+' ORDER BY b.seq DESC LIMIT 21',args).fetchall()
    items=[]
    for row in rows[:20]:
        snapshot=json.loads(row['snapshot'])
        items.append({'id':row['id'],'status':row['status'],'service':row['service'],
                      'customerName':snapshot['customerName'],'sitterName':snapshot['sitterName'],
                      'startsAt':row['starts_at'],'endsAt':row['ends_at'],
                      'serviceTotalMinor':snapshot['price']['service_total_minor'],'testOnly':snapshot.get('testOnly',True)})
    return {'items':items,'nextCursor':str(rows[19]['seq']) if len(rows)>20 else None}


def cursor(query):
    if set(query)-{'before'} or any(len(v)!=1 for v in query.values()):raise ValueError('Invalid history query')
    value=query.get('before',[None])[0]
    return conversations.number(value) if value is not None else None


def history(con, identity, query, care=False):
    before=cursor(query)
    table,key=('care_entries','id') if care else ('booking_events','revision')
    rows=con.execute('SELECT * FROM '+table+' WHERE booking_id=?'+(' AND '+key+'<?' if before is not None else '')+
                     ' ORDER BY '+key+' DESC LIMIT 31', [identity]+([before] if before is not None else [])).fetchall()
    return {'items':[booking_care.entry(r) if care else dict(r) for r in rows[:30]],
            'nextCursor':str(rows[29][key]) if len(rows)>30 else None}


def detail(con, identity):
    row=owned(con,identity)
    snapshot=json.loads(row['snapshot'])
    # Keep the same address visibility as the participant booking view.
    if row['status'] not in ('accepted','active','completed','disputed'):snapshot['address']={'address':'Toshkent'}
    case=con.execute('SELECT status,deadline FROM booking_disputes WHERE booking_id=?',(identity,)).fetchone()
    entries=[dict(r) for r in con.execute('SELECT id,amount_minor,kind,actor,reason,created FROM wallet_entries WHERE source_key IN (?,?) ORDER BY created,id',
              ('booking:'+identity+':commission','booking:'+identity+':refund'))]
    return {'id':identity,'service':row['service'],'status':row['status'],'revision':row['revision'],'readOnly':True,
            'customerId':row['customer_id'],'sitterId':row['sitter_id'],'replyDeadline':row['reply_deadline'],
            'snapshot':snapshot,'history':history(con,identity,{}),
            'commissionEntries':entries,'dispute':dict(case) if case else None}


def route(handler, con, actor, path):
    match=re.fullmatch(r'/api/admin/bookings(?:/([a-f0-9]{32})(?:/(history|care))?)?',path)
    if not match:return False
    if handler.command!='GET':raise engine.BookingError(405,'Bu bo‘lim faqat ko‘rish uchun; nizo qarori alohida oqimda')
    query=parse_qs(urlparse(handler.path).query,keep_blank_values=True)
    identity,section=match.groups()
    con.execute('BEGIN IMMEDIATE' if identity else 'BEGIN')
    if not identity:result=page(con,query)
    else:
        owned(con,identity)
        if section:result=history(con,identity,query,care=section=='care')
        else:
            if query:raise ValueError('Unexpected detail query')
            result=detail(con,identity)
        audit(con,actor,'admin-booking-'+(section or 'view'),identity)
    con.commit()
    handler.reply(200,result)
    return True
