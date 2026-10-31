"""Local/test booking API; production remains disabled pending full lifecycle QA."""
from datetime import datetime, timezone
import re
from urllib.parse import parse_qs, urlparse, unquote

import booking_engine as engine
import booking_chat
import booking_index
import booking_care
import booking_reviews
import booking_videos


def body(handler, allowed):
    value = handler.body()
    if not isinstance(value, dict) or set(value)-set(allowed):
        raise ValueError('Unexpected booking fields')
    return value


def route(handler, con, user, path, environment, data_root, *, area=None):
    if path != '/api/bookings' and not path.startswith('/api/bookings/'):
        return False
    engine.test_gate(con, environment)
    now = datetime.now(timezone.utc)
    query_string = urlparse(handler.path).query
    if handler.command == 'GET' and query_string and (
        path == '/api/bookings/policy' or re.fullmatch(
            r'/api/bookings/[a-f0-9]{32}(?:/review|/pets/[^/]+/(?:photo|passport))?', path
        )
    ):
        raise ValueError('Unexpected booking read query')
    if booking_videos.route(handler, con, user, path, data_root):
        return True
    if handler.command in ('POST','PUT','PATCH','DELETE') and urlparse(handler.path).query:
        raise ValueError('Unexpected booking mutation query')
    if booking_care.route(handler, con, user, path, now):
        return True
    review = re.fullmatch(r'/api/bookings/([a-f0-9]{32})/review', path)
    if review:
        if handler.command == 'GET':
            con.execute('BEGIN')
            result = booking_reviews.owner_view(con, review[1], user, now)
        elif handler.command == 'POST':
            result = booking_reviews.write(con, review[1], user, handler.body(), now)
            con.commit()
        else:
            raise engine.BookingError(404, 'Topilmadi')
        handler.reply(200, result)
        return True
    if path == '/api/bookings/policy' and handler.command == 'GET':
        handler.reply(200, {'version': 'elapsed-24h-v1', 'billingUnit': 'animal_started_24h',
                            'supportedPetTypes': ['It', 'Mushuk'],
                            'services': ['boarding', 'homeVisit', 'personal'], 'homeVisitAvailable': True,
                            'homeVisitTerms': {'durationAffectsPrice': False, 'fixedVisitCount': None, 'fixedVisitMinutes': None},
                            'testOnly': True, 'customerPaysSitterDirectly': True,
                            'agreementEditable': False, 'amendmentMode': 'new_quote_and_request',
                            'newRequestCancelsPrevious': False,
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
            environment=environment, now=now, instructions=data.get('instructions', ''), address=data.get('addressId'), passports=data.get('petPassports'),area=area)
        con.commit()
        handler.reply(201, result)
        return True
    if path == '/api/bookings' and handler.command == 'POST':
        data = body(handler, ['quoteId', 'requestId'])
        result = engine.request_booking(con, user, data.get('quoteId'), data.get('requestId'),
                                         environment=environment, now=now, area=area)
        result['acknowledgement'] = {
            'bookingId': result['id'], 'action': 'request',
            'requestId': data['requestId'], 'quoteId': data['quoteId'],
        }
        con.commit()
        handler.reply(200, result)
        return True
    if path == '/api/bookings' and handler.command == 'GET':
        query = parse_qs(query_string, keep_blank_values=True)
        booking_index.options(query)
        # Read-time catch-up complements the bounded background expiry worker.
        engine.expire_due(con, environment=environment, now=now, owner=user)
        con.commit()
        con.execute('BEGIN')
        handler.reply(200, booking_index.page(con, user, query))
        return True
    amendment = re.fullmatch(r'/api/bookings/([a-f0-9]{32})(?:/(change|extend))?', path)
    if amendment and ((amendment[2] and handler.command == 'POST') or
                      (not amendment[2] and handler.command in ('PUT', 'PATCH', 'DELETE'))):
        engine.owned(con, amendment[1], user)
        raise engine.BookingError(409, 'Kelishilgan buyurtma o‘zgartirilmaydi. O‘zgartirish yoki uzaytirish uchun yangi narx taklifi va alohida so‘rov kerak. Yangi so‘rov eskisini bekor qilmaydi.')
    media = re.fullmatch(r'/api/bookings/([a-f0-9]{32})/pets/([^/]{1,300})/(photo|passport)', path)
    if media and handler.command == 'GET':
        identity, pet, kind = media.groups()
        handler.reply(200,engine.animal_image(con,identity,user,unquote(pet),kind))
        return True
    match = re.fullmatch(r'/api/bookings/([a-f0-9]{32})(?:/(accept|reject|cancel|start|complete))?', path)
    if not match:
        raise engine.BookingError(404, 'Topilmadi')
    identity, action = match.groups()
    if action and handler.command == 'POST':
        data = body(handler, ['revision', 'requestId', 'reason'])
        result = engine.act(con, user, identity, action, data.get('revision'), data.get('requestId'),
                            reason=data.get('reason', ''), environment=environment, now=now, area=area)
        if action in ('accept', 'reject', 'cancel'):
            # The engine verified the actor and fingerprint (also on replay).
            # A deadline crossing records expiry instead of the requested action.
            event = next(e for e in result['history'] if e['revision'] == data['revision'] + 1)
            if not ((event['action'] == action and event['actor'] == user) or
                    (event['action'] == 'expire' and event['actor'] == 'system')):
                raise RuntimeError('Booking acknowledgement event mismatch')
            result['acknowledgement'] = {
                'bookingId': identity, 'requestId': data['requestId'], 'action': action,
                'eventAction': event['action'], 'eventRevision': event['revision'],
            }
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
