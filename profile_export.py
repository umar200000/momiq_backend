"""Owner-only portable profile fields. Media, credentials and other parties are excluded."""
from datetime import datetime,timezone
import json


def fields(record, names):
    if not isinstance(record,dict):
        return {}
    return {name:record[name] for name in names if name in record and
            (record[name] is None or type(record[name]) in (str,int,float,bool))}


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
    if not con.in_transaction:
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
    return {
        'format':'momiq-profile-v1','ownerId':owner,'generatedAt':datetime.now(timezone.utc).isoformat(),
        'profile':{**fields(account.get('profile'),('first','last')),'phone':row['phone']},
        'addresses':[fields(a,('id','label','address','apartment','lat','lon')) for a in account.get('addresses',[])],
        'pets':[fields(p,('id','type','otherType','name','age','sex','breed','notes','archived','vaccinations','allergies','medications','behavior','emergencyName','emergencyPhone'))
                for p in account.get('pets',[])],
        'sitterProfile':sitter_fields,
        'preferences':{**fields(account,('language',)),
                       'notifications':fields(account.get('notifications'),('orders','chat','video'))},
    }
