"""Bind an administrator's appeal closure to the decision actually reviewed.

Capturing a decision never changes content visibility, booking state or money.
"""
import hashlib
import json
import re

import booking_engine as engine
import catalog


def context(con, target):
    identity = target['id']
    snapshot = {'kind': target['kind'], 'id': identity, 'available': False}
    event = None
    if target['kind'] == 'listing':
        owner, service = identity.rsplit(':', 1)
        if con.execute('SELECT 1 FROM users WHERE id=?', (owner,)).fetchone():
            document = catalog.document(con, owner)
            item = next((item for item in document['listings'] if item['type'] == service), None)
            state = document['moderation'].get(service, {})
            row = con.execute('SELECT * FROM listing_moderation WHERE user_id=? AND service=?', (owner, service)).fetchone()
            snapshot.update(available=item is not None, sourceRevision=document['_revision'],
                            status=state.get('status', 'missing'))
            if row:
                snapshot['decision'] = {'status': row['status'], 'reason': row['reason'], 'decidedAt': row['reviewed_at']}
            audit = con.execute("SELECT id,target FROM audit WHERE action IN ('listing-approve','listing-reject','listing-suspend') AND CASE WHEN json_valid(target) THEN json_extract(target,'$.id') END=? ORDER BY id DESC LIMIT 1", (identity,)).fetchone()
            if audit:
                event = 'audit:'+str(audit['id'])
                snapshot['decisionRevision'] = json.loads(audit['target']).get('revision')
    else:
        row = con.execute('SELECT * FROM booking_reviews WHERE id=?', (int(identity),)).fetchone()
        if row:
            snapshot.update(available=True, sourceRevision=row['revision'], hidden=bool(row['hidden']), withdrawn=bool(row['withdrawn']))
            history = con.execute("SELECT revision,payload,created FROM review_history WHERE review_id=? AND action='moderate' ORDER BY revision DESC LIMIT 1", (row['id'],)).fetchone()
            if history:
                payload = json.loads(history['payload'])
                snapshot['decision'] = {'hidden': payload['hidden'], 'reason': payload['reason'], 'decidedAt': history['created']}
                snapshot['decisionRevision'] = history['revision']
                event = 'review:'+identity+':'+str(history['revision'])
    value = {'snapshot': snapshot, 'sourceEvent': event}
    return {**value, 'version': hashlib.sha256(engine.encode(value).encode()).hexdigest()}


def checked_context(con, target, version):
    if version is None:
        raise engine.BookingError(428, 'Amaldagi qarorni yuklash uchun panelni yangilang')
    if not isinstance(version, str) or not re.fullmatch(r'[a-f0-9]{64}', version):
        raise ValueError('Invalid decision version')
    current = context(con, target)
    if version != current['version']:
        raise engine.BookingError(409, 'Moderatsiya qarori o‘zgargan. Murojaatni yangilang')
    return current


def attach(con, ticket, message, value, created):
    con.execute('INSERT INTO support_resolutions VALUES(?,?,?,?,?,?)',
                (message, ticket, value['version'], value['sourceEvent'], engine.encode(value['snapshot']), created))


def message_rows(con, ticket, messages, admin=False):
    if not messages:
        return {}
    ids = [row['id'] for row in messages]
    rows = con.execute('SELECT * FROM support_resolutions WHERE ticket_id=? AND message_id IN ('+','.join('?' for _ in ids)+')', [ticket, *ids]).fetchall()
    return {row['message_id']: {'snapshot': json.loads(row['snapshot']), 'created': row['created'],
                               **({'sourceEvent': row['source_event'], 'version': row['source_version']} if admin else {})}
            for row in rows}
