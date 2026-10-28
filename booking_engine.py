"""Booking transaction core, integrated with the local/test HTTP/mobile flow.

Started-24-hour pricing was approved on 2026-10-28. Production and hosted staging
are still rejected until the remaining service lifecycle is integrated.
Each mutation owns one transaction; callers use a connection context to commit or
roll back. No function commits halfway through a booking/wallet change.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import hashlib
import json
import re
import secrets

import booking_rules as rules
import catalog
import conversations
import wallet
import notifications
import sitter_availability
import booking_capacity
from media_validation import validate_photo


class BookingError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)


@dataclass(frozen=True)
class DailyPolicy:
    """Approved: every started 24 hours, independent of calendar boundaries."""
    version: str = 'elapsed-24h-v1'


def stamp(value):
    return rules.utc(value).isoformat(timespec='microseconds')


def parse(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError('Explicit zoned timestamp required')
    return rules.utc(datetime.fromisoformat(value))


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def begin(con):
    if con.in_transaction:
        raise RuntimeError('Booking operation requires a fresh transaction')
    con.execute('BEGIN IMMEDIATE')


def test_gate(con, environment):
    actual = con.execute("SELECT value FROM runtime_metadata WHERE key='environment'").fetchone()
    if environment not in ('local', 'test') or not actual or actual[0] not in ('local', 'test'):
        raise BookingError(503, 'Bron xizmati hozir faqat local/test muhitida')


def account(con, user, role=None):
    row = con.execute('SELECT account,blocked FROM users WHERE id=?', (user,)).fetchone()
    if not row or row['blocked']:
        raise BookingError(403, 'Hisob faol emas')
    if role and not con.execute('SELECT 1 FROM user_roles WHERE user_id=? AND role=?', (user, role)).fetchone():
        raise BookingError(403, 'Hisob roli mos emas')
    return json.loads(row['account'])


def listing(con, customer, listing_id, environment):
    item = next((item for item in catalog.iter_profiles(con, environment) if item['id'] == listing_id), None)
    if not item or item['userId'] == customer or conversations.blocked_pair(con, customer, item['userId']):
        raise BookingError(409, 'Enaga yangi buyurtma qabul qilmayapti')
    return item


def check_schedule(con, sitter, start, end):
    message = sitter_availability.reason(account(con, sitter, 'sitter'), start, end)
    if message:
        raise BookingError(409, message)


def prepare_quote(con, customer, listing_id, pet_ids, starts_at, ends_at, *,
                  policy, environment, now, instructions='', address=None, passports=None):
    """Read all prices/animals/settings on the server. No client price/day argument."""
    if type(policy) is not DailyPolicy or policy.version != 'elapsed-24h-v1':
        raise BookingError(503, 'Tasdiqlangan sana siyosati kerak')
    if (not isinstance(pet_ids, list) or not 1 <= len(pet_ids) <= 30
            or any(not isinstance(p, str) or not p or len(p) > 100 for p in pet_ids)
            or len(set(pet_ids)) != len(pet_ids)):
        raise ValueError('Unique owned animals required')
    start, end, current = parse(starts_at), parse(ends_at), rules.utc(now)
    if start <= current or end <= start or end-start > timedelta(days=365):
        raise ValueError('Invalid service interval')
    if not isinstance(instructions, str) or len(instructions) > 4000:
        raise ValueError('Invalid care instructions')
    passports = {} if passports is None else passports
    if (not isinstance(passports, dict) or any(p not in pet_ids for p in passports)
            or any(not isinstance(v,str) or not v for v in passports.values())):
        raise ValueError('Passport must belong to a selected animal')
    begin(con)
    test_gate(con, environment)
    owner = account(con, customer, 'customer')
    conversations.quota(con, customer, 'booking_quote', 30)
    profile = owner.get('profile', {})
    if not profile.get('first', '').strip() or not profile.get('last', '').strip():
        raise BookingError(409, 'Mijoz profilini to‘ldiring')
    item = listing(con, customer, listing_id, environment)
    check_schedule(con, item['userId'], start, end)
    service = catalog.SERVICES[item['service']]
    pets = {p['id']: p for p in owner.get('pets', []) if not p.get('archived', False)}
    if any(p not in pets for p in pet_ids):
        raise BookingError(404, 'Hayvon topilmadi')
    if any(pets[p].get('type') not in ('It','Mushuk') or pets[p].get('type') not in item['pets'] for p in pet_ids):
        raise BookingError(409, 'Enaga bu hayvon turini qabul qilmaydi')
    capacity = 30 if service == 'homeVisit' else rules.integer(item['capacity'], 1, 30)
    if len(pet_ids) > capacity:
        raise BookingError(409, 'Hayvonlar soni sig‘imdan ortiq')
    # Visiting uses an owned saved address, never a client-supplied arbitrary
    # address object. Other services use the sitter's private listing address.
    raw = json.loads(con.execute('SELECT data FROM listings WHERE user_id=?', (item['userId'],)).fetchone()[0])
    if service == 'homeVisit':
        if not isinstance(address, str) or not address or len(address)>100:
            raise ValueError('Owned address ID required')
        private = next((a for a in owner.get('addresses', []) if a['id']==address), None)
        if not private:
            raise BookingError(404, 'Manzil topilmadi')
    else:
        private = next(v for v in raw['listings'] if v['type'] == service)['location']
        if address is not None:
            raise ValueError('Listing supplies the handover address for this service')
    days = rules.billable_days(start, end)
    settings = wallet.settings(con)
    price = rules.price_snapshot(service, [rules.AnimalRate(p, item['price']*100) for p in sorted(pet_ids)],
                                 days, settings['commissionBps'], settings['version'])
    media = []
    total_media = 0
    for pet_id in sorted(pet_ids):
        for kind, raw_image in [('photo', pets[pet_id].get('photo')), ('passport', passports.get(pet_id))]:
            if raw_image is None:
                continue
            image = validate_photo(raw_image)
            if image is None:
                raise ValueError('Invalid booking media')
            total_media += len(image)
            if total_media > 16*1024*1024:
                raise BookingError(413, 'Buyurtma rasmlarining umumiy hajmini kamaytiring')
            media.append((pet_id, kind, hashlib.sha256(image.encode()).hexdigest(), image))
    detail = {
        'price': asdict(price), 'listingId': listing_id, 'listingRevision': catalog.revision(con, item['userId']),
        'sitterName': item['name'], 'customerName': profile['first']+' '+profile['last'][:1]+'.',
        'pets': [dict({k: v for k, v in pets[p].items() if k != 'photo'},
                     hasPhoto=bool(pets[p].get('photo')), hasPassport=p in passports) for p in sorted(pet_ids)],
        'instructions': instructions.strip(), 'address': private, 'capacity': capacity,
        'startsAt': stamp(start), 'endsAt': stamp(end), 'datePolicy': policy.version,
        'testOnly': True, 'customerPaysSitterDirectly': True,
        'visitTerms': {'durationAffectsPrice': False, 'fixedVisitCount': None, 'fixedVisitMinutes': None} if service == 'homeVisit' else None,
    }
    identity = secrets.token_hex(16)
    con.execute('INSERT INTO booking_quotes VALUES(?,?,?,?,?,?,?,1)',
                (identity, customer, item['userId'], service, encode(detail), stamp(current),
                 stamp(min(current+timedelta(minutes=10), start))))
    for pet_id, kind, digest, image in media:
        con.execute('INSERT OR IGNORE INTO booking_media VALUES(?,?)', (digest, image))
        con.execute('INSERT INTO booking_quote_media VALUES(?,?,?,?)', (identity, pet_id, kind, digest))
    return quote_view(con, identity, customer)


def animal_image(con, identity, user, animal_id, kind):
    row = owned(con, identity, user)
    if kind not in ('photo', 'passport'):
        raise ValueError('Invalid media kind')
    image = con.execute('SELECT m.image FROM booking_quote_media q JOIN booking_media m ON m.hash=q.media_hash WHERE q.quote_id=? AND q.animal_id=? AND q.kind=?',
                        (row['quote_id'], animal_id, kind)).fetchone()
    if not image:
        raise BookingError(404, 'Rasm topilmadi')
    return {'image': image['image']}


def quote_view(con, identity, customer):
    row = con.execute('SELECT * FROM booking_quotes WHERE id=? AND customer_id=?', (identity, customer)).fetchone()
    if not row:
        raise BookingError(404, 'Narx taklifi topilmadi')
    detail = json.loads(row['snapshot'])
    # Exact private address is disclosed only after acceptance, not by a quote.
    detail['address'] = {'address': 'Toshkent'}
    return {'id': row['id'], 'created': row['created'], 'expiresAt': row['expires_at'], 'snapshot': detail}


def owned(con, identity, user):
    row = con.execute('SELECT * FROM bookings WHERE id=? AND (customer_id=? OR sitter_id=?)',
                      (identity, user, user)).fetchone()
    if not row:
        raise BookingError(404, 'Buyurtma topilmadi')
    return row


def view(con, identity, user):
    row = owned(con, identity, user)
    detail = json.loads(con.execute('SELECT snapshot FROM booking_quotes WHERE id=?', (row['quote_id'],)).fetchone()[0])
    if row['status'] not in ('accepted', 'active', 'completed', 'disputed'):
        detail['address'] = {'address': 'Toshkent'}
    # The owner can review their snapshot; a proposed sitter only needs the
    # emergency contact after acceptance while care/support remains relevant.
    if user != row['customer_id'] and row['status'] not in ('accepted','active','disputed'):
        for pet in detail.get('pets',[]):
            pet.pop('emergencyName', None)
            pet.pop('emergencyPhone', None)
    events = [dict(e) for e in con.execute('SELECT revision,actor,action,reason,status,created FROM booking_events WHERE booking_id=? ORDER BY revision', (identity,))]
    peer = row['sitter_id'] if user == row['customer_id'] else row['customer_id']
    confirmations = {action: {'mine': any(e['action']==action and e['actor']==user for e in events),
                              'peer': any(e['action']==action and e['actor']==peer for e in events)}
                     for action in ('start', 'complete')}
    return {'id': row['id'], 'status': row['status'], 'revision': row['revision'],
            'myRole': 'customer' if user == row['customer_id'] else 'sitter',
            'replyDeadline': row['reply_deadline'], 'snapshot': detail, 'history': events,
            'confirmations': confirmations}


def record(con, row, actor, action, reason, current):
    con.execute('INSERT INTO booking_events VALUES(?,?,?,?,?,?,?)',
                (row['id'], row['revision'], actor, action, reason, row['status'], stamp(current)))
    con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',
                (actor, 'booking-'+action, encode({'id': row['id'], 'revision': row['revision'], 'reason': reason}), stamp(current)))
    for recipient in (row['customer_id'], row['sitter_id']):
        notifications.publish(con, recipient, f"booking:{row['id']}:{row['revision']}:{recipient}",
                              'booking', row['id'], row['status'], reason)


def retry_key(request_id, payload):
    if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,100}', request_id):
        raise ValueError('Stable requestId required')
    return hashlib.sha256(encode(payload).encode()).hexdigest()


def previous(con, user, request_id, fingerprint):
    row = con.execute('SELECT * FROM booking_requests WHERE actor=? AND request_id=?', (user, request_id)).fetchone()
    if row and row['fingerprint'] != fingerprint:
        raise BookingError(409, 'Request ID boshqa amal uchun ishlatilgan')
    return view(con, row['booking_id'], user) if row else None


def remember(con, user, request_id, fingerprint, identity):
    con.execute('INSERT INTO booking_requests VALUES(?,?,?,?)', (user, request_id, fingerprint, identity))


def request_booking(con, customer, quote_id, request_id, *, environment, now):
    if not isinstance(quote_id, str) or not re.fullmatch(r'[a-f0-9]{32}', quote_id):
        raise ValueError('Valid quote ID required')
    fingerprint = retry_key(request_id, {'action': 'request', 'quoteId': quote_id})
    current = rules.utc(now)
    begin(con)
    test_gate(con, environment)
    account(con, customer, 'customer')
    old = previous(con, customer, request_id, fingerprint)
    if old:
        return old
    quote = con.execute('SELECT * FROM booking_quotes WHERE id=? AND customer_id=?', (quote_id, customer)).fetchone()
    if not quote:
        raise BookingError(404, 'Narx taklifi topilmadi')
    conversations.quota(con, customer, 'booking_request', 20)
    existing = con.execute('SELECT id FROM bookings WHERE quote_id=?', (quote_id,)).fetchone()
    if existing:
        remember(con, customer, request_id, fingerprint, existing['id'])
        return view(con, existing['id'], customer)
    if current >= parse(quote['expires_at']):
        raise BookingError(409, 'Narx taklifi muddati tugagan')
    detail = json.loads(quote['snapshot'])
    listing(con, customer, detail['listingId'], environment)
    check_schedule(con, quote['sitter_id'], parse(detail['startsAt']), parse(detail['endsAt']))
    # A quote pins the price, but removal/archive/type changes of selected pets
    # must not create a request against animals the account no longer owns.
    pets = {p['id']: p for p in account(con, customer).get('pets', []) if not p.get('archived', False)}
    if any(p['type'] not in ('It','Mushuk') or p['id'] not in pets or p['type'] != pets[p['id']]['type'] for p in detail['pets']):
        raise BookingError(409, 'Hayvon ma’lumoti o‘zgargan; yangi taklif oling')
    identity = secrets.token_hex(16)
    con.execute('INSERT INTO bookings(id,quote_id,customer_id,sitter_id,service,starts_at,ends_at,reply_deadline,status,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (identity, quote_id, customer, quote['sitter_id'], quote['service'], detail['startsAt'], detail['endsAt'],
                 stamp(rules.reply_deadline(current, parse(detail['startsAt']))), 'pending', stamp(current), stamp(current)))
    for p in detail['pets']:
        con.execute('INSERT INTO booking_animals VALUES(?,?,?)', (identity, customer, p['id']))
    row = owned(con, identity, customer)
    record(con, row, customer, 'request', '', current)
    remember(con, customer, request_id, fingerprint, identity)
    return view(con, identity, customer)


def change(con, row, status, actor, action, reason, current):
    con.execute('UPDATE bookings SET status=?,revision=revision+1,updated=? WHERE id=? AND revision=?',
                (status, stamp(current), row['id'], row['revision']))
    updated = owned(con, row['id'], row['customer_id'])
    record(con, updated, actor, action, reason, current)
    return updated


def expire_due(con, *, environment, now, limit=200, owner=None, identity=None):
    rules.integer(limit, 1, 1000)
    begin(con)
    test_gate(con, environment)
    clause = ''; args = [stamp(now)]
    if owner is not None:
        clause += ' AND (customer_id=? OR sitter_id=?)'; args.extend([owner, owner])
    if identity is not None:
        clause += ' AND id=?'; args.append(identity)
    args.append(limit)
    rows = con.execute("SELECT * FROM bookings WHERE status='pending' AND reply_deadline<=?"+clause+" ORDER BY reply_deadline LIMIT ?", args).fetchall()
    for row in rows:
        change(con, row, 'expired', 'system', 'expire', 'Javob muddati tugadi', now)
    return len(rows)


def check_capacity(con, row, detail, current):
    current_listing = json.loads(con.execute('SELECT data FROM listings WHERE user_id=?', (row['sitter_id'],)).fetchone()[0])
    item = next((i for i in current_listing['listings'] if i['type'] == row['service']), None)
    if not item or not item['active']:
        raise BookingError(409, 'E’lon faol emas')
    cap = 30 if row['service'] == 'homeVisit' else (1 if row['service'] == 'personal' else min(detail['capacity'], item['capacity']))
    if len(detail['pets']) > booking_capacity.remaining(con,row['sitter_id'],row['service'],
            parse(row['starts_at']),parse(row['ends_at']),cap,current,exclude=row['id']):
        raise BookingError(409, 'Tanlangan vaqtda bo‘sh joy yo‘q yoki oldingi parvarish tugamagan')
    conflict = con.execute("SELECT 1 FROM bookings b JOIN booking_animals a ON a.booking_id=b.id JOIN booking_animals wanted ON wanted.customer_id=a.customer_id AND wanted.animal_id=a.animal_id WHERE wanted.booking_id=? AND b.id!=? AND b.status IN ('accepted','active','disputed') AND ((b.starts_at<? AND b.ends_at>?) OR (b.status='active' AND b.ends_at<=?)) LIMIT 1",
                           (row['id'], row['id'], row['ends_at'], row['starts_at'], stamp(current))).fetchone()
    if conflict:
        raise BookingError(409, 'Hayvon uchun shu vaqtda boshqa bron bor')


def act(con, user, identity, action, revision, request_id, *, reason='', environment, now):
    if action not in ('accept', 'reject', 'cancel', 'start', 'complete'):
        raise ValueError('Unsupported booking action')
    if type(revision) is not int or revision < 0:
        raise BookingError(428, 'Joriy buyurtma versiyasi kerak')
    if not isinstance(reason, str) or len(reason) > 1000 or (action in ('reject', 'cancel') and not reason.strip()):
        raise ValueError('Reason required')
    reason = reason.strip()
    fingerprint = retry_key(request_id, {'booking': identity, 'action': action, 'revision': revision, 'reason': reason})
    current = rules.utc(now)
    begin(con)
    test_gate(con, environment)
    account(con, user)
    row = owned(con, identity, user)
    if action in ('accept', 'reject') and user != row['sitter_id']:
        raise BookingError(403, 'Faqat enaga qabul yoki rad etadi')
    old = previous(con, user, request_id, fingerprint)
    if old:
        return old
    if row['revision'] != revision:
        raise BookingError(409, 'Buyurtma o‘zgargan; qayta yuklang')
    if row['status'] == 'pending' and current >= parse(row['reply_deadline']):
        # Commit the expiry as a normal result; throwing would roll it back.
        change(con, row, 'expired', 'system', 'expire', 'Javob muddati tugadi', current)
        remember(con, user, request_id, fingerprint, identity)
        return view(con, identity, user)
    detail = json.loads(con.execute('SELECT snapshot FROM booking_quotes WHERE id=?', (row['quote_id'],)).fetchone()[0])
    price = detail['price']
    commission = price['commission_minor']
    if action == 'accept':
        if row['status'] != 'pending':
            raise BookingError(409, 'Buyurtmani qabul qilib bo‘lmaydi')
        account(con, row['customer_id'], 'customer')
        account(con, row['sitter_id'], 'sitter')
        listing(con, row['customer_id'], detail['listingId'], environment)
        check_schedule(con, row['sitter_id'], parse(row['starts_at']), parse(row['ends_at']))
        check_capacity(con, row, detail, current)
        if wallet.balance(con, user) < max(rules.MINIMUM_BALANCE_MINOR, commission):
            raise BookingError(409, 'Balans minimum yoki komissiyaga yetmaydi')
        if commission:
            wallet.post_entry(con, user, -commission, 'commission', 'booking:'+identity+':commission', user, 'Buyurtma qabul qilindi')
        status = 'accepted'
    elif action == 'reject':
        if row['status'] != 'pending':
            raise BookingError(409, 'Faqat kutilayotgan so‘rov rad etiladi')
        status = 'rejected'
    elif action in ('start', 'complete'):
        required = 'accepted' if action == 'start' else 'active'
        if row['status'] != required:
            raise BookingError(409, 'Bu holatda tasdiqlash mumkin emas')
        if current < parse(row['starts_at']) or (action == 'start' and current >= parse(row['ends_at'])):
            raise BookingError(409, 'Tasdiqlash vaqti mos emas; kechikkan boshlash uchun admin ko‘rigi kerak')
        if con.execute('SELECT 1 FROM booking_events WHERE booking_id=? AND actor=? AND action=?', (identity, user, action)).fetchone():
            raise BookingError(409, 'Siz allaqachon tasdiqlagansiz; ikkinchi tomon javobi kutilmoqda')
        peer = row['sitter_id'] if user == row['customer_id'] else row['customer_id']
        peer_confirmed = con.execute('SELECT 1 FROM booking_events WHERE booking_id=? AND actor=? AND action=?', (identity, peer, action)).fetchone()
        if action == 'complete':
            started = con.execute("SELECT MAX(created) FROM booking_events WHERE booking_id=? AND action='start'", (identity,)).fetchone()[0]
            if not started or current < parse(started):
                raise BookingError(409, 'Yakunlash boshlash tasdig‘idan oldin bo‘la olmaydi')
        status = ('active' if action == 'start' else 'completed') if peer_confirmed else required
        role = 'mijoz' if user == row['customer_id'] else 'enaga'
        reason = ('Xizmat boshlanishini tasdiqladi: ' if action == 'start' else 'Xizmat yakunini tasdiqladi: ') + role
    else:
        if row['status'] not in ('pending', 'accepted'):
            raise BookingError(409, 'Buyurtmani bu holatda bekor qilib bo‘lmaydi')
        if row['status'] == 'accepted' and current >= parse(row['starts_at']):
            raise BookingError(409, 'Xizmat vaqti boshlandi; admin ko‘rigi kerak')
        if row['status'] == 'accepted' and commission:
            wallet.post_entry(con, row['sitter_id'], commission, 'commission_refund', 'booking:'+identity+':refund', user, reason)
        from booking_disputes import late_cancel
        late_cancel(con, row, user, current)
        status = 'cancelled'
    change(con, row, status, user, action, reason, current)
    if action == 'start' and status == 'active':
        from video_followup import schedule
        schedule(con,row,current)
    remember(con, user, request_id, fingerprint, identity)
    return view(con, identity, user)
