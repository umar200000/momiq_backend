"""Local/test booking API; production remains disabled pending full lifecycle QA."""
from datetime import datetime, timezone
import re
from urllib.parse import parse_qs, urlparse, unquote

import booking_engine as engine
import booking_chat
import conversations


def body(handler, allowed):
    value = handler.body()
    if not isinstance(value, dict) or set(value)-set(allowed):
        raise ValueError('Unexpected booking fields')
    return value


def route(handler, con, user, path, environment):
    if path != '/api/bookings' and not path.startswith('/api/bookings/'):
        return False
    engine.test_gate(con, environment)
    now = datetime.now(timezone.utc)
    if path == '/api/bookings/policy' and handler.command == 'GET':
        handler.reply(200, {'version': 'elapsed-24h-v1', 'billingUnit': 'animal_started_24h',
                            'services': ['boarding', 'homeVisit', 'personal'], 'homeVisitAvailable': True,
                            'homeVisitTerms': {'durationAffectsPrice': False, 'fixedVisitCount': None, 'fixedVisitMinutes': None},
                            'testOnly': True, 'customerPaysSitterDirectly': True,
                            'quoteValiditySeconds': 600})
        return True
    chat = re.fullmatch(r'/api/bookings/([a-f0-9]{32})/conversation', path)
    if chat and handler.command == 'POST':
        body(handler, [])
        result = booking_chat.open_chat(con, chat[1], user, environment)
        con.commit()
        handler.reply(200, result)
        return True
    if path == '/api/bookings/quotes' and handler.command == 'POST':
        data = body(handler, ['listingId', 'petIds', 'startsAt', 'endsAt', 'instructions', 'addressId', 'petPassports'])
        result = engine.prepare_quote(con, user, data.get('listingId'), data.get('petIds'),
            data.get('startsAt'), data.get('endsAt'), policy=engine.DailyPolicy(),
            environment=environment, now=now, instructions=data.get('instructions', ''), address=data.get('addressId'), passports=data.get('petPassports'))
        con.commit()
        handler.reply(201, result)
        return True
    if path == '/api/bookings' and handler.command == 'POST':
        data = body(handler, ['quoteId', 'requestId'])
        result = engine.request_booking(con, user, data.get('quoteId'), data.get('requestId'),
                                         environment=environment, now=now)
        con.commit()
        handler.reply(200, result)
        return True
    if path == '/api/bookings' and handler.command == 'GET':
        query = parse_qs(urlparse(handler.path).query)
        status = query.get('status', ['all'])[0]
        if status not in ('all', 'pending', 'accepted', 'cancelled', 'rejected', 'expired', 'active', 'completed', 'disputed'):
            raise ValueError('Invalid booking status')
        cursor = query.get('before', [None])[0]
        before = conversations.number(cursor) if cursor is not None else None
        # Expiry is lazy, durable and bounded. Explicit worker scheduling remains
        # separate; a stale pending action still expires itself atomically.
        engine.expire_due(con, environment=environment, now=now, owner=user)
        con.commit()
        con.execute('BEGIN')
        args = [user, user]; clause = '(customer_id=? OR sitter_id=?)'
        if before is not None:
            clause += ' AND seq<?'; args.append(before)
        if status != 'all':
            clause += ' AND status=?'; args.append(status)
        rows = con.execute('SELECT id,seq FROM bookings WHERE '+clause+' ORDER BY seq DESC LIMIT 21', args).fetchall()
        # List excludes private agreement/address; details require a separate GET.
        items = []
        for row in rows[:20]:
            item = engine.view(con, row['id'], user)
            items.append({k: item[k] for k in ('id', 'status', 'revision', 'myRole', 'replyDeadline')})
        handler.reply(200, {'items': items, 'nextCursor': str(rows[19]['seq']) if len(rows)>20 else None})
        return True
    media = re.fullmatch(r'/api/bookings/([a-f0-9]{32})/pets/([^/]{1,300})/(photo|passport)', path)
    if media and handler.command == 'GET':
        identity, pet, kind = media.groups()
        handler.reply(200,engine.animal_image(con,identity,user,unquote(pet),kind))
        return True
    match = re.fullmatch(r'/api/bookings/([a-f0-9]{32})(?:/(accept|reject|cancel))?', path)
    if not match:
        raise engine.BookingError(404, 'Topilmadi')
    identity, action = match.groups()
    if action and handler.command == 'POST':
        data = body(handler, ['revision', 'requestId', 'reason'])
        result = engine.act(con, user, identity, action, data.get('revision'), data.get('requestId'),
                            reason=data.get('reason', ''), environment=environment, now=now)
        con.commit()
        handler.reply(200, result)
        return True
    if not action and handler.command == 'GET':
        engine.owned(con, identity, user)
        engine.expire_due(con, environment=environment, now=now, identity=identity, limit=1)
        con.commit()
        con.execute('BEGIN')
        handler.reply(200, engine.view(con, identity, user))
        return True
    raise engine.BookingError(404, 'Topilmadi')
