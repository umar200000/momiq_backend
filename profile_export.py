"""Owner-only portable profile fields. Media, credentials and other parties are excluded."""
from datetime import datetime,timezone
import json


def fields(record, names):
    if not isinstance(record,dict):
        return {}
    return {name:record[name] for name in names if name in record and
            (record[name] is None or type(record[name]) in (str,int,float,bool))}


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
