"""Bounded participant-only booking search; never indexes private care notes."""
import json
import unicodedata

import conversations

STATES = ('pending', 'accepted', 'active', 'disputed', 'completed', 'cancelled', 'rejected', 'expired')
BUCKETS = {'all': STATES, 'pending': ('pending',), 'ongoing': ('accepted', 'active', 'disputed'),
           'history': ('completed', 'cancelled', 'rejected', 'expired')}


def folded(value):
    return unicodedata.normalize('NFKC', str(value or '')).casefold()


def options(query):
    if set(query) - {'before', 'status', 'bucket', 'q'} or any(len(v)!=1 for v in query.values()):
        raise ValueError('Invalid booking filters')
    cursor = query.get('before', [None])[0]
    before = conversations.number(cursor) if cursor is not None else None
    status, bucket = query.get('status', ['all'])[0], query.get('bucket', ['all'])[0]
    text = query.get('q', [''])[0].strip()
    if status not in ('all', *STATES) or bucket not in BUCKETS or len(text)>80 or any(ord(c)<32 for c in text):
        raise ValueError('Invalid booking filters')
    return before, status, bucket, folded(text)


def page(con, user, query, chat=None):
    before, status, bucket, text = options(query)
    con.create_function('booking_fold', 1, folded, deterministic=True)
    clause = '(b.customer_id=? OR b.sitter_id=?)'; args = [user, user]
    if chat is not None:
        clause += ' AND b.customer_id=? AND b.sitter_id=? AND b.service=?'
        args.extend([chat['customer_id'], chat['sitter_id'], chat['service']])
    if before is not None:
        clause += ' AND b.seq<?'; args.append(before)
    if status != 'all':
        clause += ' AND b.status=?'; args.append(status)
    if bucket != 'all':
        clause += ' AND b.status IN ('+','.join('?' for _ in BUCKETS[bucket])+')'
        args.extend(BUCKETS[bucket])
    if text:
        clause += " AND (instr(booking_fold(b.id),?)>0 OR instr(booking_fold(CASE WHEN b.customer_id=? THEN json_extract(q.snapshot,'$.sitterName') ELSE json_extract(q.snapshot,'$.customerName') END),?)>0 OR EXISTS (SELECT 1 FROM json_each(q.snapshot,'$.pets') pet WHERE instr(booking_fold(json_extract(pet.value,'$.name')),?)>0))"
        args.extend([text, user, text, text])
    rows = con.execute('SELECT b.*,q.snapshot FROM bookings b JOIN booking_quotes q ON q.id=b.quote_id WHERE '+clause+' ORDER BY b.seq DESC LIMIT 21', args).fetchall()
    items = []
    for row in rows[:20]:
        data = json.loads(row['snapshot']); customer = row['customer_id']==user
        items.append({'id':row['id'], 'status':row['status'], 'revision':row['revision'],
                      'myRole':'customer' if customer else 'sitter', 'replyDeadline':row['reply_deadline'],
                      'startsAt':row['starts_at'], 'endsAt':row['ends_at'], 'service':row['service'],
                      'peerName':data['sitterName'] if customer else data['customerName'],
                      'pets':[{'name':p.get('name',''), 'type':p['type']} for p in data['pets']],
                      'serviceTotalMinor':data['price']['service_total_minor']})
    return {'items':items, 'nextCursor':str(rows[19]['seq']) if len(rows)>20 else None}
