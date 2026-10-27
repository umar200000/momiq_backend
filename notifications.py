"""Authenticated in-app transactional notices. No external push is sent here."""
import json
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse


class NotificationError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def publish(con, user, source, kind, target, status, reason):
    if not con.in_transaction:
        raise RuntimeError('Notice must share the business transaction')
    if kind not in ('wallet_topup', 'listing'):
        raise ValueError('Unsupported notice kind')
    payload = json.dumps({'kind': kind, 'targetId': target, 'status': status, 'reason': reason}, sort_keys=True)
    existing = con.execute('SELECT user_id,payload FROM notifications WHERE source_key=?', (source,)).fetchone()
    if existing:
        if existing['user_id'] != user or existing['payload'] != payload:
            raise ValueError('Notice source reused with different content')
        return
    con.execute('INSERT INTO notifications(user_id,source_key,payload,created) VALUES(?,?,?,?)',
                (user, source, payload, datetime.now(timezone.utc).isoformat()))


def route(handler, con, user, path):
    if path == '/api/notifications' and handler.command == 'GET':
        query = parse_qs(urlparse(handler.path).query)
        cursor = query.get('before', [None])[0]
        if cursor is not None and not re.fullmatch(r'[1-9][0-9]{0,17}', cursor):
            raise ValueError('Invalid notice cursor')
        con.execute('BEGIN')
        args = [user]
        clause = 'user_id=?'
        if cursor:
            clause += ' AND id<?'; args.append(int(cursor))
        rows = con.execute('SELECT * FROM notifications WHERE '+clause+' ORDER BY id DESC LIMIT 21', args).fetchall()
        unread = con.execute('SELECT COUNT(*) FROM notifications WHERE user_id=? AND read_at IS NULL', (user,)).fetchone()[0]
        handler.reply(200, {'items': [dict(json.loads(r['payload']), id=str(r['id']), created=r['created'], readAt=r['read_at']) for r in rows[:20]],
                            'nextCursor': str(rows[19]['id']) if len(rows) > 20 else None, 'unreadCount': unread})
        return True
    match = re.fullmatch(r'/api/notifications/([1-9][0-9]{0,17})/read', path)
    if match and handler.command == 'POST':
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT id FROM notifications WHERE id=? AND user_id=?', (int(match[1]), user)).fetchone()
        if not row: raise NotificationError(404, 'Bildirishnoma topilmadi')
        con.execute('UPDATE notifications SET read_at=COALESCE(read_at,?) WHERE id=? AND user_id=?',
                    (datetime.now(timezone.utc).isoformat(), int(match[1]), user))
        con.commit()
        handler.reply(200, {'ok': True})
        return True
    return False
