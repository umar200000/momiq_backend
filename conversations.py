"""Private customer/sitter conversations; legacy admin support is not imported."""
import json
import re
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import catalog

PAGE = 30


class ChatError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def number(value, zero=False):
    if not isinstance(value, str) or not re.fullmatch(r'0|[1-9][0-9]{0,17}', value):
        raise ValueError('Invalid message cursor')
    result = int(value)
    if not zero and not result:
        raise ValueError('Invalid message cursor')
    return result


def participant(con, conversation, user):
    row = con.execute('SELECT * FROM conversations WHERE id=? AND (customer_id=? OR sitter_id=?)',
                      (conversation, user, user)).fetchone()
    if not row:
        raise ChatError(404, 'Suhbat topilmadi')
    return row


def blocked_pair(con, user, peer):
    return bool(con.execute('SELECT 1 FROM chat_blocks WHERE active=1 AND ((blocker_id=? AND blocked_id=?) OR (blocker_id=? AND blocked_id=?)) LIMIT 1',
                            (user, peer, peer, user)).fetchone())


def quota(con, user, kind, limit):
    # Called inside the message transaction: no premature commit or lost retry.
    key = 'conversation:' + kind + ':' + user
    row = con.execute('SELECT * FROM attempts WHERE key=?', (key,)).fetchone()
    count = row['count'] if row and row['reset'] > time.time() else 0
    if count >= limit:
        raise ChatError(429, 'Biroz kutib qayta urinib ko‘ring')
    reset = row['reset'] if count else time.time() + 60
    con.execute('INSERT OR REPLACE INTO attempts VALUES(?,?,?)', (key, count + 1, reset))


def message(row, user):
    return {'id': str(row['id']), 'senderRole': row['sender_role'],
            'mine': row['sender_id'] == user, 'text': '' if row['hidden'] else row['text'],
            'hidden': bool(row['hidden']),
            'hasImage': not row['hidden'] and row['image'] is not None, 'created': row['created'],
            'requestId': row['request_id'] if row['sender_id'] == user else None}


def summary(con, row, user):
    customer = row['customer_id'] == user
    peer = row['sitter_id'] if customer else row['customer_id']
    latest = con.execute('SELECT * FROM conversation_messages WHERE conversation_id=? ORDER BY id DESC LIMIT 1', (row['id'],)).fetchone()
    reads = dict(con.execute('SELECT user_id,last_message_id FROM conversation_reads WHERE conversation_id=?', (row['id'],)))
    delivered = dict(con.execute('SELECT user_id,last_message_id FROM conversation_deliveries WHERE conversation_id=?', (row['id'],)))
    unread = con.execute('SELECT COUNT(*) FROM conversation_messages WHERE conversation_id=? AND sender_id!=? AND id>?',
                         (row['id'], user, reads.get(user, 0))).fetchone()[0]
    blocked = con.execute('SELECT blocked FROM users WHERE id=?', (peer,)).fetchone()[0]
    own_block = con.execute('SELECT active,revision FROM chat_blocks WHERE blocker_id=? AND blocked_id=?', (user, peer)).fetchone()
    return {'id': row['id'], 'service': row['service'], 'myRole': 'customer' if customer else 'sitter',
            'peerName': row['sitter_name'] if customer else row['customer_name'],
            'created': row['created'], 'canSend': not bool(blocked) and not blocked_pair(con, user, peer), 'unreadCount': unread,
            'blockedByMe': bool(own_block['active']) if own_block else False,
            'blockRevision': own_block['revision'] if own_block else 0,
            'peerReadThrough': str(reads.get(peer, 0)), 'peerDeliveredThrough': str(max(delivered.get(peer,0),reads.get(peer,0))), 'lastMessage': message(latest, user) if latest else None}


def create(con, user, data, environment):
    listing_id = data.get('listingId')
    if not isinstance(listing_id, str) or len(listing_id) > 120 or ':' not in listing_id:
        raise ValueError('Invalid listing')
    sitter, service = listing_id.rsplit(':', 1)
    if service not in catalog.SERVICES or sitter == user:
        raise ValueError('Invalid conversation')
    # Reopening an existing contact is a read, including a lost-response retry.
    con.execute('BEGIN')
    row = con.execute('SELECT * FROM conversations WHERE customer_id=? AND sitter_id=? AND service=?', (user, sitter, service)).fetchone()
    if row:
        return summary(con, row, user)
    con.rollback()
    con.execute('BEGIN IMMEDIATE')
    # Another caller may have created this pair after the read snapshot ended.
    row = con.execute('SELECT * FROM conversations WHERE customer_id=? AND sitter_id=? AND service=?', (user, sitter, service)).fetchone()
    if row:
        return summary(con, row, user)
    if blocked_pair(con, user, sitter):
        raise ChatError(409, 'Bu hisob bilan yozishma to‘xtatilgan')
    if not con.execute("SELECT 1 FROM user_roles WHERE user_id=? AND role='customer'", (user,)).fetchone():
        raise ChatError(403, 'Mijoz profili kerak')
    profile = json.loads(con.execute('SELECT account FROM users WHERE id=?', (user,)).fetchone()[0]).get('profile', {})
    if not profile.get('first', '').strip() or not profile.get('last', '').strip():
        raise ChatError(409, 'Avval mijoz profilini to‘ldiring')
    listing = catalog.profile(con,environment,listing_id)
    if not listing:
        raise ChatError(409, 'Bu enaga hozir yangi mijoz qabul qilmayapti. Katalogni yangilang.')
    quota(con, user, 'create', 10)
    identity = secrets.token_hex(16)
    name = profile['first'] + ' ' + profile['last'][:1] + '.'
    con.execute('INSERT INTO conversations(id,customer_id,sitter_id,service,customer_name,sitter_name,created) VALUES(?,?,?,?,?,?,?)',
                (identity, user, sitter, service, name, listing['name'], timestamp()))
    return summary(con, participant(con, identity, user), user)


def send(con, user, identity, data, validate_photo):
    body = data.get('text', '')
    request = data.get('requestId')
    if not isinstance(body, str) or len(body) > 4000:
        raise ValueError('Invalid message text')
    body = body.strip()
    if not isinstance(request, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,100}', request):
        raise ValueError('Stable requestId required')
    # Authenticate ownership before spending work on decoding an attachment.
    participant(con, identity, user)
    image = validate_photo(data.get('image'))
    if not body and image is None:
        raise ValueError('Empty message')
    con.execute('BEGIN IMMEDIATE')
    row = participant(con, identity, user)
    old = con.execute('SELECT * FROM conversation_messages WHERE sender_id=? AND request_id=?', (user, request)).fetchone()
    if old:
        if old['conversation_id'] != identity or old['text'] != body or old['image'] != image:
            raise ChatError(409, 'So‘rov identifikatori boshqa xabarga tegishli')
        return message(old, user)
    peer = row['sitter_id'] if row['customer_id'] == user else row['customer_id']
    if blocked_pair(con, user, peer) or con.execute('SELECT blocked FROM users WHERE id=?', (peer,)).fetchone()[0]:
        raise ChatError(409, 'Bu hisobga hozir yozib bo‘lmaydi')
    quota(con, user, 'send', 60)
    if image:
        quota(con, user, 'image', 10)
    role = 'customer' if row['customer_id'] == user else 'sitter'
    cursor = con.execute('INSERT INTO conversation_messages(conversation_id,sender_id,sender_role,text,image,request_id,created) VALUES(?,?,?,?,?,?,?)',
                         (identity, user, role, body, image, request, timestamp()))
    # Commit the notice with the message. Never copy private message/media content
    # into the notification payload or a future lock-screen delivery.
    import notifications
    notifications.publish(con, peer, f'conversation:{cursor.lastrowid}:{peer}',
                          'conversation', identity, 'message', '')
    return message(con.execute('SELECT * FROM conversation_messages WHERE id=?', (cursor.lastrowid,)).fetchone(), user)


def route(handler, con, user, path, validate_photo, environment):
    if path != '/api/conversations' and not path.startswith('/api/conversations/'):
        return False
    query = parse_qs(urlparse(handler.path).query)
    if path == '/api/conversations':
        if handler.command == 'POST':
            result = create(con, user, handler.body(), environment)
            con.commit()
            handler.reply(200, result)
            return True
        if handler.command == 'GET':
            cursor = query.get('before', [None])[0]
            args = [user, user]
            clause = ''
            if cursor is not None:
                parts = cursor.split(':')
                if len(parts) != 2: raise ValueError('Invalid conversation cursor')
                last, seq = number(parts[0], zero=True), number(parts[1])
                clause = 'WHERE (activity<? OR (activity=? AND seq<?))'
                args.extend([last, last, seq])
            con.execute('BEGIN')
            rows = con.execute('SELECT * FROM (SELECT c.*,COALESCE((SELECT MAX(m.id) FROM conversation_messages m WHERE m.conversation_id=c.id),0) activity FROM conversations c WHERE customer_id=? OR sitter_id=?) '
                               + clause + ' ORDER BY activity DESC,seq DESC LIMIT 31', args).fetchall()
            handler.reply(200, {'items': [summary(con, r, user) for r in rows[:PAGE]],
                                'nextCursor': f"{rows[PAGE-1]['activity']}:{rows[PAGE-1]['seq']}" if len(rows) > PAGE else None})
            return True
    related = re.fullmatch(r'/api/conversations/([a-f0-9]{32})/bookings', path)
    if related and handler.command == 'GET':
        import booking_chat
        handler.reply(200, booking_chat.related(con, related[1], user, environment, query))
        return True
    match = re.fullmatch(r'/api/conversations/([a-f0-9]{32})(?:/(messages|read|received)(?:/([1-9][0-9]{0,17})/image)?)?', path)
    if not match:
        raise ChatError(404, 'Topilmadi')
    identity, action, image_id = match.groups()
    if action == 'messages' and handler.command == 'POST' and not image_id:
        result = send(con, user, identity, handler.body(), validate_photo)
        con.commit()
        handler.reply(200, result)
        return True
    if action in ('read','received') and handler.command == 'POST' and not image_id:
        data = handler.body()
        last = number(data.get('throughId'))
        con.execute('BEGIN IMMEDIATE')
        participant(con, identity, user)
        if not con.execute('SELECT 1 FROM conversation_messages WHERE conversation_id=? AND id=?', (identity, last)).fetchone():
            raise ValueError('Message not in conversation')
        if action == 'read':
            con.execute('INSERT INTO conversation_reads VALUES(?,?,?) ON CONFLICT(conversation_id,user_id) DO UPDATE SET last_message_id=MAX(last_message_id,excluded.last_message_id)', (identity, user, last))
        con.execute('INSERT INTO conversation_deliveries VALUES(?,?,?) ON CONFLICT(conversation_id,user_id) DO UPDATE SET last_message_id=MAX(last_message_id,excluded.last_message_id)', (identity,user,last))
        con.commit()
        handler.reply(200, {'ok': True})
        return True
    if handler.command != 'GET' or action in ('read','received'):
        raise ChatError(404, 'Topilmadi')
    con.execute('BEGIN')
    row = participant(con, identity, user)
    if image_id:
        image = con.execute('SELECT image FROM conversation_messages WHERE conversation_id=? AND id=? AND hidden=0', (identity, int(image_id))).fetchone()
        if not image or not image['image']: raise ChatError(404, 'Rasm topilmadi')
        handler.reply(200, {'image': image['image']})
    elif action == 'messages':
        before, after = query.get('before', [None])[0], query.get('after', [None])[0]
        if before is not None and after is not None: raise ValueError('Use one cursor')
        args = [identity]
        clause = ''
        if before is not None:
            clause = ' AND id<?'; args.append(number(before))
        elif after is not None:
            clause = ' AND id>?'; args.append(number(after, zero=True))
        ascending = after is not None
        rows = con.execute('SELECT * FROM conversation_messages WHERE conversation_id=?' + clause + ' ORDER BY id ' + ('ASC' if ascending else 'DESC') + ' LIMIT 31', args).fetchall()
        page = rows[:PAGE] if ascending else list(reversed(rows[:PAGE]))
        changes_after = query.get('changesAfter', [None])[0]
        if changes_after is not None:
            changes = con.execute('SELECT id,message_id FROM chat_changes WHERE conversation_id=? AND id>? ORDER BY id LIMIT 30', (identity, number(changes_after, zero=True))).fetchall()
            change_cursor = str(changes[-1]['id']) if changes else changes_after
        else:
            changes = []
            change_cursor = str(con.execute('SELECT COALESCE(MAX(id),0) FROM chat_changes WHERE conversation_id=?', (identity,)).fetchone()[0])
        handler.reply(200, {'items': [message(r, user) for r in page], 'hasMore': len(rows) > PAGE,
                            'redactedIds': [str(r['message_id']) for r in changes], 'changeCursor': change_cursor,
                            'conversation': summary(con, row, user)})
    else:
        handler.reply(200, summary(con, row, user))
    return True
