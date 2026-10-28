"""Participant-only links between an agreement and its service conversation."""
import json
import secrets
from datetime import datetime, timezone

import booking_engine as engine
import conversations


def open_chat(con, identity, user, environment):
    engine.begin(con)
    engine.test_gate(con, environment)
    booking = engine.owned(con, identity, user)
    row = con.execute('SELECT * FROM conversations WHERE customer_id=? AND sitter_id=? AND service=?',
                      (booking['customer_id'], booking['sitter_id'], booking['service'])).fetchone()
    if row:
        return conversations.summary(con, row, user)
    # A booking is already an established relationship: low balance or a paused
    # listing must not cut off coordination of an accepted service.
    for participant in (booking['customer_id'], booking['sitter_id']):
        engine.account(con, participant)
    if conversations.blocked_pair(con, booking['customer_id'], booking['sitter_id']):
        raise engine.BookingError(409, 'Bu hisob bilan yozishma to‘xtatilgan')
    if booking['status'] == 'pending' and datetime.now(timezone.utc) >= engine.parse(booking['reply_deadline']):
        raise engine.BookingError(409, 'So‘rovning javob muddati tugagan')
    if booking['status'] in ('expired', 'rejected', 'cancelled') and not con.execute(
            "SELECT 1 FROM booking_events WHERE booking_id=? AND action='accept'", (identity,)).fetchone():
        raise engine.BookingError(409, 'Yopilgan so‘rov uchun yangi suhbat ochilmaydi')
    conversations.quota(con, user, 'create', 10)
    agreement = json.loads(con.execute('SELECT snapshot FROM booking_quotes WHERE id=?', (booking['quote_id'],)).fetchone()[0])
    chat_id = secrets.token_hex(16)
    con.execute('INSERT INTO conversations(id,customer_id,sitter_id,service,customer_name,sitter_name,created) VALUES(?,?,?,?,?,?,?)',
                (chat_id, booking['customer_id'], booking['sitter_id'], booking['service'],
                 agreement['customerName'], agreement['sitterName'], conversations.timestamp()))
    return conversations.summary(con, conversations.participant(con, chat_id, user), user)


def related(con, identity, user, environment, before=None):
    engine.test_gate(con, environment)
    conversations.participant(con, identity, user)
    engine.expire_due(con, environment=environment, now=datetime.now(timezone.utc), owner=user)
    con.commit()
    con.execute('BEGIN')
    chat = conversations.participant(con, identity, user)
    args = [chat['customer_id'], chat['sitter_id'], chat['service']]
    clause = ''
    if before is not None:
        clause = ' AND seq<?'
        args.append(conversations.number(before))
    rows = con.execute('SELECT id,seq,status,starts_at,ends_at FROM bookings '
                       'WHERE customer_id=? AND sitter_id=? AND service=?'+clause+' ORDER BY seq DESC LIMIT 21', args).fetchall()
    # No private address, pet media or care notes in the conversation index.
    return {'items': [{'id': r['id'], 'status': r['status'], 'startsAt': r['starts_at'], 'endsAt': r['ends_at']}
                      for r in rows[:20]],
            'nextCursor': str(rows[19]['seq']) if len(rows)>20 else None}
