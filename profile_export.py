"""Owner-only portable profile fields. Media, credentials and other parties are excluded."""
from datetime import datetime,timezone
import json
import pet_safety
import sitter_availability


def fields(record, names):
    if not isinstance(record,dict):
        return {}
    return {name:record[name] for name in names if name in record and
            (record[name] is None or type(record[name]) in (str,int,float,bool))}


def read(con,owner):
    con.execute('BEGIN')
    row=con.execute('SELECT phone,account FROM users WHERE id=? AND blocked=0',(owner,)).fetchone()
    if not row:
        raise ValueError('Account unavailable')
    account=json.loads(row['account'])
    sitter = account.get('sitterProfile')
    sitter_fields = None
    if isinstance(sitter, dict):
        sitter_fields = fields(sitter, ('housing','years','about'))
        schedule = sitter.get('schedule')
        if isinstance(schedule, dict):
            days = schedule.get('days')
            start, end = schedule.get('start'), schedule.get('end')
            if (isinstance(days,list) and len(days)==7 and all(type(day) is bool for day in days)
                    and type(start) is int and type(end) is int and 0<=start<end<1440):
                sitter_fields['schedule'] = {'start':start,'end':end,'days':days,'timezone':'Asia/Tashkent'}
        if 'closedDates' in sitter:
            try:
                sitter_fields['closedDates'] = sitter_availability.closed_dates(sitter['closedDates'])
            except ValueError:
                pass  # Other valid profile fields can still be exported from an older record.
    return {
        'format':'momiq-profile-v1','ownerId':owner,'generatedAt':datetime.now(timezone.utc).isoformat(),
        'profile':{**fields(account.get('profile'),('first','last')),'phone':row['phone']},
        'addresses':[fields(a,('id','label','address','apartment','lat','lon')) for a in account.get('addresses',[])],
        'pets':[fields(p,('id','type','otherType','name','age','sex','breed','notes','archived',*pet_safety.FIELDS))
                for p in account.get('pets',[])],
        'sitterProfile':sitter_fields,
        'preferences':{**fields(account,('language',)),
                       'notifications':fields(account.get('notifications'),('orders','chat','video'))},
    }
