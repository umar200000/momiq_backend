"""Read-only two-calendar-year review. Never authorizes or performs erasure.

The owner approved the duration, not statutory exceptions. Review results are
metadata, not an export of receipts/messages and not a backup. Original evidence
and immutable database triggers remain authoritative.
"""
from datetime import datetime, timedelta, timezone
import json
import re
from urllib.parse import parse_qs, urlparse

from booking_engine import BookingError

TASHKENT = timezone(timedelta(hours=5))
TERMINAL = ('completed', 'cancelled', 'rejected', 'expired')
# Fixed SQL identifiers; client input is never interpolated as an identifier.
CATEGORIES = {
    'audit': ('audit', 'id', 'id,time'),
    'topups': ('topup_requests', 'id', 'id,user_id,status,created,reviewed_at'),
    'wallet': ('wallet_entries', 'id', 'id,user_id,created'),
    'disputes': ('booking_disputes', 'seq', 'seq,booking_id,status,created,resolved_at'),
    'support': ('support_tickets', 'seq', 'seq,id,owner_id,booking_id,status,created,updated'),
    'chatReports': ('chat_reports', 'id', 'id,reporter_id,status,created,reviewed_at'),
}


def instant(value):
    if not isinstance(value, str):
        raise ValueError('Timestamp required')
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('Timezone required')
    return parsed.astimezone(TASHKENT)


def two_years(value):
    """Local calendar anniversary; leap-day expires on Feb 28 two years later."""
    local = instant(value)
    try:
        return local.replace(year=local.year + 2)
    except ValueError:
        if local.month == 2 and local.day == 29:
            return local.replace(year=local.year + 2, day=28)
        raise


def decision(anchors, holds, now):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Timezone required')
    holds = set(holds)
    parsed = []
    for value in anchors:
        try:
            stamp = instant(value)
            if stamp > now:
                holds.add('future_timestamp')
            parsed.append(stamp)
        except (ValueError, TypeError, OverflowError):
            holds.add('invalid_timestamp')
    anchor = max(parsed) if parsed else None
    expiry = None
    if anchor:
        try:
            expiry = two_years(anchor.isoformat())
        except (ValueError, OverflowError):
            holds.add('invalid_timestamp')
    else:
        holds.add('invalid_timestamp')
    return {
        'state': 'held' if holds else ('expired_review' if now >= expiry else 'retained'),
        'anchorAt': anchor.isoformat() if anchor else None,
        'reviewAt': expiry.isoformat() if expiry else None,
        'holds': sorted(holds),
        'deletionAllowed': False,
    }


def history_dates(con, sql, args, anchors, holds):
    rows = con.execute(sql + ' LIMIT 501', args).fetchall()
    if len(rows) > 500:
        holds.append('history_requires_separate_review')
    anchors.extend(row[0] for row in rows[:500])


def booking_context(con, booking_id, anchors, holds):
    row = con.execute('SELECT status,updated FROM bookings WHERE id=?', (booking_id,)).fetchone()
    if not row:
        holds.append('missing_booking')
        return
    if row['status'] not in TERMINAL:
        holds.append('active_booking')
    anchors.append(row['updated'])
    case = con.execute('SELECT status,resolved_at FROM booking_disputes WHERE booking_id=?', (booking_id,)).fetchone()
    if case:
        if case['status'] != 'resolved':
            holds.append('open_dispute')
        else:
            anchors.append(case['resolved_at'])
    if con.execute("SELECT 1 FROM support_tickets WHERE booking_id=? AND status!='resolved' LIMIT 1", (booking_id,)).fetchone():
        holds.append('open_support')
    # Later resolved appeals extend review of the original booking evidence.
    history_dates(con, "SELECT updated FROM support_tickets WHERE booking_id=? AND status='resolved'",
                  (booking_id,), anchors, holds)


def owner_context(con, owner, anchors, holds):
    # A conservative account-level hold: a complaint need not yet be linked to a
    # particular ledger entry. This report never infers that funds may be erased.
    if con.execute("SELECT 1 FROM bookings WHERE (customer_id=? OR sitter_id=?) AND status NOT IN ('completed','cancelled','rejected','expired') LIMIT 1", (owner, owner)).fetchone():
        holds.append('active_booking')
    if con.execute("SELECT 1 FROM booking_disputes d JOIN bookings b ON b.id=d.booking_id WHERE (b.customer_id=? OR b.sitter_id=?) AND d.status!='resolved' LIMIT 1", (owner, owner)).fetchone():
        holds.append('open_dispute')
    if con.execute("SELECT 1 FROM support_tickets s LEFT JOIN bookings b ON b.id=s.booking_id WHERE (s.owner_id=? OR b.customer_id=? OR b.sitter_id=?) AND s.status!='resolved' LIMIT 1", (owner, owner, owner)).fetchone():
        holds.append('open_support')
    history_dates(con, "SELECT updated FROM bookings WHERE (customer_id=? OR sitter_id=?) AND status IN ('completed','cancelled','rejected','expired')",
                  (owner, owner), anchors, holds)
    history_dates(con, "SELECT d.resolved_at FROM booking_disputes d JOIN bookings b ON b.id=d.booking_id WHERE (b.customer_id=? OR b.sitter_id=?) AND d.status='resolved'",
                  (owner, owner), anchors, holds)
    history_dates(con, "SELECT s.updated FROM support_tickets s LEFT JOIN bookings b ON b.id=s.booking_id WHERE (s.owner_id=? OR b.customer_id=? OR b.sitter_id=?) AND s.status='resolved'",
                  (owner, owner, owner), anchors, holds)


def assess(con, category, row, now):
    anchors, holds = [], []
    if category == 'audit':
        anchors.append(row['time'])
    else:
        anchors.append(row['created'])
    if category == 'topups':
        if row['status'] not in ('approved', 'rejected'):
            holds.append('unresolved_topup')
        else:
            anchors.append(row['reviewed_at'])
        for table in ('topup_history', 'wallet_corrections'):
            history_dates(con, f'SELECT created FROM {table} WHERE topup_id=?', (row['id'],), anchors, holds)
        owner_context(con, row['user_id'], anchors, holds)
    elif category == 'wallet':
        owner_context(con, row['user_id'], anchors, holds)
        # Corrections and original entries form one financial evidence chain.
        history_dates(con, 'SELECT created FROM wallet_corrections WHERE original_entry_id=? OR entry_id=?',
                      (row['id'], row['id']), anchors, holds)
    elif category == 'disputes':
        if row['status'] != 'resolved':
            holds.append('open_dispute')
        else:
            anchors.append(row['resolved_at'])
        booking_context(con, row['booking_id'], anchors, holds)
    elif category == 'support':
        if row['status'] != 'resolved':
            holds.append('open_support')
        anchors.append(row['updated'])
        if row['booking_id']:
            booking_context(con, row['booking_id'], anchors, holds)
    elif category == 'chatReports':
        if row['status'] == 'open':
            holds.append('open_report')
        else:
            anchors.append(row['reviewed_at'])
        history_dates(con, 'SELECT created FROM chat_report_history WHERE report_id=?', (row['id'],), anchors, holds)
        owner_context(con, row['reporter_id'], anchors, holds)
    return decision(anchors, holds, now)


def parameters(query, archive=False):
    allowed = {'before'} if archive else {'category', 'before'}
    if set(query) - allowed or any(len(v) != 1 for v in query.values()):
        raise ValueError('Arxiv filtri noto‘g‘ri')
    category = 'audit' if archive else query.get('category', ['audit'])[0]
    if category not in CATEGORIES:
        raise ValueError('Arxiv toifasi noto‘g‘ri')
    before = query.get('before', [None])[0]
    if before is not None:
        pattern = r'[a-f0-9]{32}' if category in ('topups', 'wallet') else r'[1-9][0-9]{0,17}'
        if not re.fullmatch(pattern, before):
            raise ValueError('Arxiv sahifasi noto‘g‘ri')
    return category, before


def page(con, category, before, now, archive=False):
    table, key, columns = CATEGORIES[category]
    if archive:
        columns = 'id,actor,action,target,time'
    rows = con.execute(f'SELECT {columns} FROM {table}' + (f' WHERE {key}<?' if before else '') +
                       f' ORDER BY {key} DESC LIMIT 51', (before,) if before else ()).fetchall()
    items = []
    for row in rows[:50]:
        item = {'id': str(row[key]), **assess(con, category, row, now)}
        if archive:
            item['record'] = dict(row)
        items.append(item)
    return {'category': category, 'mode': 'review_only', 'policyVersion': 'owner-two-years-v1',
            'calendarYears': 2, 'timezone': 'Asia/Tashkent', 'asOf': now.isoformat(),
            'deletionEnabled': False, 'pending': ['statutory_exceptions', 'purge_approval'],
            'items': items, 'nextCursor': str(rows[49][key]) if len(rows) > 50 else None}


def route(handler, con, actor, path):
    if path not in ('/api/admin/retention-review', '/api/admin/audit-archive'):
        return False
    if getattr(handler, 'operator_role', None) != 'administrator':
        raise BookingError(403, 'Faqat administrator uchun')
    if handler.command != 'GET':
        raise BookingError(405, 'Arxiv faqat o‘qiladi')
    archive = path.endswith('/audit-archive')
    category, before = parameters(parse_qs(urlparse(handler.path).query, keep_blank_values=True), archive)
    now = datetime.now(timezone.utc)
    con.execute('BEGIN IMMEDIATE')
    result = page(con, category, before, now, archive)
    con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',
                (actor, 'audit-archive-view' if archive else 'retention-review',
                 json.dumps({'category': category, 'before': before, 'count': len(result['items'])}), now.isoformat()))
    con.commit()
    handler.reply(200, result)
    return True
