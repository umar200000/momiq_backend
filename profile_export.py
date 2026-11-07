"""Owner-only portable profile fields. Media, credentials and other parties are excluded."""
from datetime import datetime,timezone
import json
import math
import pet_safety
import sitter_availability


def fields(record, names):
    if not isinstance(record,dict):
        return {}
    return {name:record[name] for name in names if name in record and
            (record[name] is None or type(record[name]) in (str,int,bool) or
             (type(record[name]) is float and math.isfinite(record[name])))}


def records(value):
    # Older optional collections can be null or damaged. Never iterate a map's
    # keys/string characters as records, or rewrite the source while exporting.
    return [item for item in value if isinstance(item,dict)] if isinstance(value,list) else []


def owner_services(con, owner):
    row = con.execute('SELECT data FROM listings WHERE user_id=?', (owner,)).fetchone()
    if row is None:
        return []
    try:
        document = json.loads(row[0])
    except (TypeError, ValueError):
        return []  # A damaged legacy draft must not prevent the owner exporting their profile.
    items = document.get('listings') if isinstance(document, dict) else None
    if not isinstance(items, list):
        return []
    services = []
    for item in items:
        if not isinstance(item, dict) or item.get('type') not in ('boarding','homeVisit','personal'):
            continue
        service = {'type': item['type']}
        if type(item.get('price')) is int:
            service['price'] = item['price']
        if type(item.get('active')) is bool:
            service['active'] = item['active']
        if item['type']=='boarding' and type(item.get('capacity')) is int:
            service['capacity'] = item['capacity']
        if isinstance(item.get('pets'), list):
            service['pets'] = [pet for pet in item['pets'] if pet in ('dog','cat')]
        services.append(service)
    return services


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
        services = owner_services(con, owner)
        if services:
            sitter_fields['services'] = services
        for key in ('schedule', 'closedDates'):
            if key in sitter:
                try:
                    sitter_fields.update(sitter_availability.calendar_fields({key:sitter[key]}))
                except ValueError:
                    pass  # Keep other exportable fields from an older record.
    return {
        'format':'momiq-profile-v1','ownerId':owner,'generatedAt':datetime.now(timezone.utc).isoformat(),
        'profile':{**fields(account.get('profile'),('first','last')),'phone':row['phone']},
        'addresses':[fields(a,('id','label','address','apartment','lat','lon')) for a in records(account.get('addresses'))],
        'pets':[fields(p,('id','type','otherType','name','age','sex','breed','notes','archived',*pet_safety.FIELDS))
                for p in records(account.get('pets'))],
        'sitterProfile':sitter_fields,
        'preferences':{**fields(account,('language',)),
                       'notifications':fields(account.get('notifications'),('orders','chat','video'))},
    }
