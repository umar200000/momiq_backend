"""Tashkent sitter calendar validation for profile writes."""
from datetime import date
import re


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


def preserve_omitted(before, after, incoming):
    """Older profile clients must not silently erase the new calendar."""
    target = after.get('sitterProfile')
    source = incoming.get('sitterProfile')
    if target is not None and isinstance(source, dict):
        previous = before.get('sitterProfile') or {}
        for key in ('schedule', 'closedDates'):
            if key not in source and key in previous:
                target[key] = previous[key]
