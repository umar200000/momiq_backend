"""Tashkent handover hours and start-date closures, shared by discovery/booking."""
from datetime import date, datetime, timedelta, timezone
import re

ZONE = timezone(timedelta(hours=5), 'Asia/Tashkent')


def closed_dates(value):
    if not isinstance(value, list) or len(value) > 366:
        raise ValueError('Yopiq sanalar ro‘yxati 366 tadan oshmasin')
    for item in value:
        if not isinstance(item, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', item):
            raise ValueError('Yopiq sana YYYY-MM-DD shaklida bo‘lsin')
        date.fromisoformat(item)
    if len(set(value)) != len(value):
        raise ValueError('Yopiq sana takrorlanmasin')
    return sorted(value)


def public(account):
    sitter = account.get('sitterProfile') or {}
    return {'timezone': 'Asia/Tashkent', 'schedule': sitter.get('schedule'),
            'closedDates': sitter.get('closedDates', []),
            'hoursApplyTo': 'endpoints', 'closedDatesApplyTo': 'start',
            'overnightAllowed': True}


def preserve_omitted(before, after, incoming):
    """Older profile clients must not silently erase the new calendar."""
    target = after.get('sitterProfile')
    source = incoming.get('sitterProfile')
    if target is not None and isinstance(source, dict) and 'closedDates' not in source:
        previous = (before.get('sitterProfile') or {}).get('closedDates')
        if previous is not None:
            target['closedDates'] = previous


def reason(account, start, end):
    if start.utcoffset() is None or end.utcoffset() is None or end <= start:
        raise ValueError('Vaqt mintaqasi bilan to‘g‘ri oraliq kerak')
    start, end = start.astimezone(ZONE), end.astimezone(ZONE)
    availability = public(account)
    if start.date().isoformat() in availability['closedDates']:
        return 'Enaga shu sanada boshlanadigan yangi buyurtmalarni qabul qilmaydi'
    schedule = availability['schedule']
    # An unset schedule makes no promise of 24/7 availability. It adds no
    # handover restriction; capacity and sitter acceptance still apply.
    if schedule is not None:
        for point in (start, end):
            if not schedule['days'][point.weekday()]:
                return 'Olib kelish yoki olib ketish kuni enaganing ish kuniga mos emas'
            minute = point.hour * 60 + point.minute
            if (minute < schedule['start'] or minute > schedule['end']
                    or (minute == schedule['end'] and (point.second or point.microsecond))):
                return 'Olib kelish va olib ketish vaqti enaganing ish soatiga mos bo‘lsin (Toshkent vaqti)'
    return None


def interval(params):
    """Optional zoned discovery interval. Never silently accept one endpoint."""
    values = [params.get(key, []) for key in ('startsAt', 'endsAt')]
    if values == [[], []]:
        return None
    if any(len(value) != 1 or len(value[0]) > 40 for value in values):
        raise ValueError('Qidiruvning boshlanish va tugash vaqti kerak')
    start, end = (datetime.fromisoformat(value[0]) for value in values)
    if start.utcoffset() is None or end.utcoffset() is None or not timedelta(0) < end-start <= timedelta(days=365):
        raise ValueError('Qidiruv sanalari noto‘g‘ri')
    return start, end
