"""Approved daily report windows; callers pass server UTC, never phone time."""
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation

TASHKENT = timezone(timedelta(hours=5))
SLOTS = {'morning': (time(7), time(11)), 'evening': (time(18), time(22))}
MAX_BYTES = 32 * 1024 * 1024


def duration_ms(value):
    try:
        seconds = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError('Video davomiyligi aniqlanmadi') from error
    if not seconds.is_finite() or not Decimal(10) <= seconds <= Decimal(60):
        raise ValueError('Video 10–60 soniya bo‘lishi kerak')
    return int(seconds * 1000)


def window(day, slot):
    if slot not in SLOTS:
        raise ValueError('Video vaqti noto‘g‘ri')
    start, end = SLOTS[slot]
    return (datetime.combine(day, start, TASHKENT), datetime.combine(day, end, TASHKENT))


def policy(now):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Server vaqti zonali bo‘lsin')
    current = now.astimezone(TASHKENT)
    return {'timezone': 'Asia/Tashkent', 'serverTime': now.astimezone(timezone.utc).isoformat(),
            'today': current.date().isoformat(), 'minSeconds': 10, 'maxSeconds': 60,
            'maxBytes': MAX_BYTES, 'slots': [
                {'slot': slot, 'opensAt': start.isoformat(), 'closesAt': end.isoformat(),
                 'open': start <= current < end}
                for slot in SLOTS for start, end in [window(current.date(), slot)]]}


def require_window(day, slot, now):
    current = policy(now)
    if day != current['today'] or not any(s['slot'] == slot and s['open'] for s in current['slots']):
        raise ValueError('Video Toshkent vaqti bilan 07:00–11:00 yoki 18:00–22:00 oralig‘ida yuboriladi')

