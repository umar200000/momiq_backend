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


def calendar_fields(sitter):
    result = {}
    schedule = sitter.get('schedule')
    if 'closedDates' in sitter:
        result['closedDates'] = closed_dates(sitter['closedDates'])
    if schedule is not None:
        if not isinstance(schedule,dict): raise ValueError('Jadval noto‘g‘ri')
        days, start, end = schedule.get('days'), schedule.get('start'), schedule.get('end')
        if not isinstance(days,list) or len(days)!=7 or any(type(v) is not bool for v in days): raise ValueError('Hafta kunlari noto‘g‘ri')
        if type(start) is not int or type(end) is not int or not 0<=start<end<1440: raise ValueError('Ish vaqti noto‘g‘ri')
        result['schedule'] = {'days':days,'start':start,'end':end,'timezone':'Asia/Tashkent'}
    return result


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
    if target is not None and isinstance(source, dict):
        previous = before.get('sitterProfile') or {}
        for key in ('schedule', 'closedDates'):
            if key not in source and key in previous:
                target[key] = previous[key]



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


def service_interval(starts_at, ends_at):
    def parse(value):
        if not isinstance(value, str) or len(value) > 40:
            raise ValueError('Vaqt mintaqasi bilan sana kerak')
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            raise ValueError('Vaqt mintaqasi bilan sana kerak')
        try:
            utc = parsed.astimezone(timezone.utc)
            # The same instant must fit both the database timestamp and the handover calendar.
            utc.astimezone(ZONE)
        except OverflowError:
            raise ValueError('Sana ruxsat etilgan oraliqdan tashqarida') from None
        return utc

    start, end = parse(starts_at), parse(ends_at)
    if not timedelta(0) < end - start <= timedelta(days=365):
        raise ValueError('Xizmat sanalari noto‘g‘ri')
    return start, end


def interval(params):
    """Optional zoned discovery interval. Never silently accept one endpoint."""
    values = [params.get(key, []) for key in ('startsAt', 'endsAt')]
    if values == [[], []]:
        return None
    if any(len(value) != 1 for value in values):
        raise ValueError('Qidiruvning boshlanish va tugash vaqti kerak')
    return service_interval(values[0][0], values[1][0])
