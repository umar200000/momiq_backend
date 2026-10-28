"""Participant-only care journal. Reports are sitter statements, not proof of care.

The immutable booking agreement stays intact. Later customer instructions and
sitter corrections append separate versioned entries; local preferences are
never imported as real reports. Video and scheduled reminders are separate work.
"""
from datetime import date, timedelta, timezone
import json
import re

import booking_engine as engine
import conversations

CATEGORIES = ('food', 'water', 'walk', 'medicine', 'other')
VISIBLE = ('accepted', 'active', 'completed', 'disputed', 'cancelled')
TASHKENT = timezone(timedelta(hours=5))


def today(now):
    return engine.rules.utc(now).astimezone(TASHKENT).date().isoformat()


def access(con, identity, user):
    engine.account(con, user)
    booking = engine.view(con, identity, user)
    if booking['status'] not in VISIBLE:
        raise engine.BookingError(409, 'Parvarish faqat qabul qilingan buyurtmada ochiladi')
    return booking


def day_value(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('Use YYYY-MM-DD')
    return date.fromisoformat(value).isoformat()


def text(value, limit, required=False):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise ValueError('Invalid care text')
    value = value.strip()
    if required and not value:
        raise ValueError('Reason required')
    return value


def entry(row):
    return {'id': str(row['id']), 'petId': row['pet_id'], 'kind': row['kind'],
            'day': row['day'], 'category': row['category'], 'revision': row['revision'],
            'actorRole': 'customer' if row['kind'] == 'instructions' else 'sitter',
            'payload': json.loads(row['payload']), 'created': row['created']}


def latest(con, identity, pet, kind, day, category):
    return con.execute('SELECT * FROM care_entries WHERE booking_id=? AND pet_id=? AND kind=? AND day=? AND category=? ORDER BY revision DESC LIMIT 1',
                       (identity, pet, kind, day, category)).fetchone()


def overview(con, identity, user, day, now):
    if not con.in_transaction:
        con.execute('BEGIN')
    booking = access(con, identity, user)
    day = today(now) if day is None else day_value(day)
    if day > today(now):
        raise ValueError('Future report date')
    pets = []
    for animal in booking['snapshot']['pets']:
        pet = animal['id']
        instruction = latest(con, identity, pet, 'instructions', '', '')
        reports = [latest(con, identity, pet, 'report', day, category) for category in CATEGORIES]
        pets.append({'id': pet, 'name': animal.get('name') or animal['type'],
                     'originalNotes': animal.get('notes') or '',
                     'originalMedication': animal.get('medications') or '',
                     'instructions': entry(instruction) if instruction else None,
                     'reports': [entry(row) for row in reports if row]})
    return {'bookingId': identity, 'status': booking['status'], 'myRole': booking['myRole'],
            'timezone': 'Asia/Tashkent', 'today': today(now), 'day': day,
            'originalInstructions': booking['snapshot'].get('instructions') or '',
            'canEditInstructions': booking['myRole'] == 'customer' and booking['status'] in ('accepted', 'active'),
            'canReport': booking['myRole'] == 'sitter' and booking['status'] == 'active' and day == today(now),
            'pets': pets}


def history(con, identity, user, before=None):
    if not con.in_transaction:
        con.execute('BEGIN')
    access(con, identity, user)
    args = [identity]
    clause = ''
    if before is not None:
        if not isinstance(before, str) or not re.fullmatch(r'[1-9][0-9]{0,17}', before):
            raise ValueError('Invalid history cursor')
        clause = ' AND id<?'; args.append(int(before))
    rows = con.execute('SELECT * FROM care_entries WHERE booking_id=?'+clause+' ORDER BY id DESC LIMIT 31', args).fetchall()
    return {'items': [entry(row) for row in rows[:30]],
            'nextCursor': str(rows[29]['id']) if len(rows) > 30 else None}


def save(con, identity, user, data, now):
    allowed = {'petId', 'kind', 'day', 'category', 'revision', 'requestId', 'payload'}
    if not isinstance(data, dict) or set(data) != allowed:
        raise ValueError('Unexpected care fields')
    pet, kind, day, category = (data[key] for key in ('petId', 'kind', 'day', 'category'))
    revision, payload = data['revision'], data['payload']
    if not isinstance(pet, str) or type(revision) is not int or revision < 0 or not isinstance(payload, dict):
        raise ValueError('Invalid care entry')
    if kind == 'instructions':
        if day != '' or category != '' or set(payload) != {*CATEGORIES, 'reason'}:
            raise ValueError('Invalid instructions')
        payload = {key: text(payload[key], 2000 if key in CATEGORIES else 500, key == 'reason') for key in payload}
    elif kind == 'report':
        day = day_value(day)
        if category not in CATEGORIES or set(payload) != {'state', 'note'} or payload['state'] not in ('done', 'skipped', 'undone'):
            raise ValueError('Invalid report')
        payload = {'state': payload['state'], 'note': text(payload['note'], 2000, payload['state'] != 'done' or revision > 0)}
    else:
        raise ValueError('Invalid care kind')
    fingerprint = engine.retry_key(data['requestId'], {'booking': identity, **data})
    engine.begin(con)
    booking = access(con, identity, user)
    prior = con.execute('SELECT * FROM care_entries WHERE actor=? AND request_id=?', (user, data['requestId'])).fetchone()
    if prior:
        if prior['fingerprint'] != fingerprint:
            raise engine.BookingError(409, 'Bu so‘rov boshqa yozuv uchun ishlatilgan')
        return entry(prior)
    if not any(p['id'] == pet for p in booking['snapshot']['pets']):
        raise engine.BookingError(404, 'Hayvon bu buyurtmaga tegishli emas')
    if kind == 'instructions':
        if booking['myRole'] != 'customer' or booking['status'] not in ('accepted', 'active'):
            raise engine.BookingError(403, 'Ko‘rsatmalarni faqat mijoz yangilaydi')
    elif booking['myRole'] != 'sitter' or booking['status'] != 'active' or day != today(now):
        raise engine.BookingError(403, 'Hisobot faqat faol buyurtmada bugungi kun uchun kiritiladi')
    old = latest(con, identity, pet, kind, day, category)
    if revision != (old['revision'] if old else 0):
        raise engine.BookingError(409, 'Yozuv o‘zgargan. Yangilab, qayta tekshiring')
    if kind == 'report' and not old and payload['state'] == 'undone':
        raise ValueError('There is no earlier report to reverse')
    conversations.quota(con, user, 'care_entry', 60)
    cursor = con.execute('INSERT INTO care_entries(booking_id,pet_id,kind,day,category,revision,actor,request_id,fingerprint,payload,created) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                         (identity,pet,kind,day,category,revision+1,user,data['requestId'],fingerprint,engine.encode(payload),engine.stamp(now)))
    con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',
                (user,'care-'+kind,engine.encode({'bookingId':identity,'entryId':cursor.lastrowid}),engine.stamp(now)))
    return entry(con.execute('SELECT * FROM care_entries WHERE id=?',(cursor.lastrowid,)).fetchone())


def route(handler, con, user, path, now):
    match = re.fullmatch(r'/api/bookings/([a-f0-9]{32})/care(?:/(history))?', path)
    if not match:
        return False
    from urllib.parse import parse_qs, urlparse
    query = parse_qs(urlparse(handler.path).query, keep_blank_values=True)
    allowed = {'before'} if match[2] else {'day'}
    if set(query)-allowed or any(len(v) != 1 for v in query.values()):
        raise ValueError('Invalid care query')
    if handler.command == 'GET':
        result = history(con,match[1],user,query.get('before',[None])[0]) if match[2] else overview(con,match[1],user,query.get('day',[None])[0],now)
    elif handler.command == 'POST' and not match[2] and not query:
        result = save(con,match[1],user,handler.body(),now)
        con.commit()
    else:
        raise engine.BookingError(404, 'Topilmadi')
    handler.reply(200,result)
    return True
