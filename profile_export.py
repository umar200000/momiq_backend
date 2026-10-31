"""Owner-only portable profile fields. Media, credentials and other parties are excluded."""
from datetime import datetime,timezone
import json
import pet_safety


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
    return {
        'format':'momiq-profile-v1','ownerId':owner,'generatedAt':datetime.now(timezone.utc).isoformat(),
        'profile':{**fields(account.get('profile'),('first','last')),'phone':row['phone']},
        'addresses':[fields(a,('id','label','address','apartment','lat','lon')) for a in account.get('addresses',[])],
        'pets':[fields(p,('id','type','otherType','name','age','sex','breed','notes','archived',*pet_safety.FIELDS))
                for p in account.get('pets',[])],
        'sitterProfile':fields(account['sitterProfile'],('housing','years','about')) if account.get('sitterProfile') else None,
        'preferences':{**fields(account,('language',)),
                       'notifications':fields(account.get('notifications'),('orders','chat','video'))},
    }
