"""Paged operator indexes; private account/listing details are loaded and audited on demand."""
import base64
from datetime import datetime, timezone
import hashlib
import json
import re
from urllib.parse import parse_qs, urlparse

import catalog


def required_reason(reason):
    if not isinstance(reason,str) or not reason.strip() or len(reason)>1000:
        raise ValueError('Amal sababi majburiy (1–1000 belgi)')
    return reason.strip()


def change_reason(data):
    """Validate the admin write envelope before any write lock or profile decode."""
    if set(data)-{'account','blocked','_revision','reason'} or not ({'account','blocked'} & set(data)):
        raise ValueError('Profil o‘zgarishi maydonlari noto‘g‘ri')
    if 'blocked' in data and type(data['blocked']) is not bool:
        raise ValueError('Holat noto‘g‘ri')
    return required_reason(data.get('reason'))


def change_record(uid,before,after,blocked_before,blocked_after,revision,reason):
    def snapshot(account,blocked,version):
        profile=account.get('profile') or {};photo=profile.get('photo')
        result={'blocked':bool(blocked),'revision':version,
                'accountSha256':hashlib.sha256(json.dumps(account,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
        if before.get('profile')!=after.get('profile'):
            result['profile']={'first':profile.get('first'),'last':profile.get('last'),
                               'photoSha256':hashlib.sha256(photo.encode()).hexdigest() if photo else None}
        return result
    return {'userId':uid,'reason':reason,
            'changedFields':sorted(key for key in set(before)|set(after) if before.get(key)!=after.get(key)),
            'before':snapshot(before,blocked_before,revision),
            'after':snapshot(after,blocked_after,revision+1)}


def filters(params, kind):
    if set(params)-{'q','status','role','service','after'} or any(len(v)!=1 for v in params.values()):
        raise ValueError('Index query is invalid')
    selected={key:params.get(key,[default])[0] for key,default in [('q',''),('status','all'),('role','all'),('service','all')]}
    selected['q']=selected['q'].strip().casefold()
    statuses=('all','active','blocked') if kind=='users' else ('all','draft','pending','approved','rejected','suspended','archived')
    if (len(selected['q'])>100 or selected['status'] not in statuses or selected['role'] not in ('all','customer','sitter')
            or selected['service'] not in ('all',*catalog.SERVICES)
            or (kind=='users' and selected['service']!='all') or (kind=='listings' and selected['role']!='all')):
        raise ValueError('Index filter is invalid')
    digest=hashlib.sha256(json.dumps([kind,selected],sort_keys=True).encode()).hexdigest()[:24]
    after=''
    if 'after' in params:
        token=params['after'][0]
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,512}',token):raise ValueError('Invalid cursor')
        try:cursor=json.loads(base64.urlsafe_b64decode(token+'='*(-len(token)%4)))
        except (ValueError,UnicodeDecodeError) as error:raise ValueError('Invalid cursor') from error
        if (not isinstance(cursor,dict) or set(cursor)!={'last','query'} or cursor['query']!=digest or not isinstance(cursor['last'],str)
                or not re.fullmatch(r'[a-f0-9]{1,64}'+(r':(boarding|homeVisit|personal)' if kind=='listings' else ''),cursor['last'])):
            raise ValueError('Filters changed; reload the first page')
        after=cursor['last']
    return selected,digest,after


def listing_detail(con, row, item, data):
    account=json.loads(row['account'])
    return dict(item,id=row['id']+':'+item['type'],userId=row['id'],phone=row['phone'],profile=account['profile'],
                blocked=bool(row['blocked']),housing=data['housing'],updated=row['updated'],_revision=data['_revision'],
                moderation=data['moderation'][item['type']],missing=catalog.completeness(account,item))


def index(con, kind, params, roles_for):
    selected,digest,after=filters(params,kind)
    con.execute('BEGIN')
    result=[]
    if kind=='users':
        for row in con.execute('SELECT * FROM users WHERE id>? ORDER BY id',(after,)):
            roles=roles_for(con,row['id'])
            if selected['role']!='all' and selected['role'] not in roles:continue
            if selected['status']!='all' and bool(row['blocked'])!=(selected['status']=='blocked'):continue
            account=json.loads(row['account']);profile=account.get('profile') or {}
            if selected['q'] not in ' '.join([row['id'],row['phone'],profile.get('first',''),profile.get('last','')]).casefold():continue
            result.append({'id':row['id'],'phone':row['phone'],'blocked':bool(row['blocked']),'created':row['created'],'roles':roles,'_summary':True,
                           'account':{'profile':{'first':profile.get('first',''),'last':profile.get('last',''),'photo':None}}})
            if len(result)>20:break
    else:
        after_key=tuple(after.split(':',1)) if after else ('','')
        for row in con.execute('SELECT u.*,l.updated FROM users u JOIN listings l ON l.user_id=u.id WHERE u.id>=? ORDER BY u.id',(after_key[0],)):
            account=json.loads(row['account']);profile=account.get('profile') or {}
            if selected['q'] not in ' '.join([row['id'],row['phone'],profile.get('first',''),profile.get('last','')]).casefold():continue
            data=catalog.document(con,row['id'])
            for item in sorted(data['listings'],key=lambda value:value['type']):
                if (row['id'],item['type'])<=after_key:continue
                if selected['service']!='all' and item['type']!=selected['service']:continue
                moderation=data['moderation'][item['type']]
                if selected['status']!='all' and moderation['status']!=selected['status']:continue
                result.append({'id':row['id']+':'+item['type'],'userId':row['id'],'type':item['type'],'phone':row['phone'],
                               'profile':{'first':profile.get('first',''),'last':profile.get('last','')},'blocked':bool(row['blocked']),
                               'active':item['active'],'price':item['price'],'moderation':moderation,'_summary':True})
                if len(result)>20:break
            if len(result)>20:break
    more=len(result)>20;result=result[:20]
    cursor=base64.urlsafe_b64encode(json.dumps({'last':result[-1]['id'],'query':digest},separators=(',',':')).encode()).decode().rstrip('=') if more else None
    response={kind:result,'nextCursor':cursor}
    if kind=='users':
        # Legacy contact references only; modern contacts are loaded for the selected account.
        response['sitters']={r['id']:json.loads(r['profile']).get('name','') for r in con.execute('SELECT id,profile FROM sitters')}
    return response


def audit_index(con,actor,kind,selected,after):
    metadata={'status':selected['status'],'role':selected['role'],'service':selected['service'],
              'searchPresent':bool(selected['q']),'after':after or None}
    con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',
                (actor,'admin-'+kind+'-index',json.dumps(metadata),datetime.now(timezone.utc).isoformat()))


def route(handler, con, actor, path, account_snapshot, roles_for):
    if handler.command!='GET':return False
    match=re.fullmatch(r'/api/admin/(users|listings)',path)
    if match:
        params=parse_qs(urlparse(handler.path).query,keep_blank_values=True)
        selected,_,after=filters(params,match[1])
        result=index(con,match[1],params,roles_for)
        audit_index(con,actor,match[1],selected,after)
        con.commit();handler.reply(200,result)
        return True
    match=re.fullmatch(r'/api/admin/(users|listings)/([a-f0-9]{1,64})(?:/(boarding|homeVisit|personal))?',path)
    if not match:return False
    kind,uid,service=match.groups()
    if (kind=='users' and service) or (kind=='listings' and not service):return False
    con.execute('BEGIN IMMEDIATE')
    row=con.execute('SELECT u.*,l.updated FROM users u LEFT JOIN listings l ON l.user_id=u.id WHERE u.id=?',(uid,)).fetchone()
    if not row:
        handler.reply(404,{'error':'Hisob topilmadi'});return True
    if kind=='users':
        user={'id':uid,'phone':row['phone'],'blocked':bool(row['blocked']),'created':row['created'],'roles':roles_for(con,uid),'account':account_snapshot(con,row)}
        contacts={r[0] for r in con.execute('SELECT DISTINCT sitter FROM messages WHERE user_id=?',(uid,))}
        names={}
        for contact in contacts:
            if ':' in contact:
                owner=con.execute('SELECT account FROM users WHERE id=?',(contact.split(':',1)[0],)).fetchone()
                if owner:
                    profile=json.loads(owner[0]).get('profile') or {}
                    names[contact]=' '.join([profile.get('first',''),profile.get('last','')]).strip()
            else:
                old=con.execute('SELECT profile FROM sitters WHERE id=?',(contact,)).fetchone()
                if old:names[contact]=json.loads(old[0]).get('name','')
        response={'user':user,'sitters':names}
    else:
        data=catalog.document(con,uid)
        item=next((item for item in data['listings'] if item['type']==service),None)
        if not item:
            handler.reply(404,{'error':'E’lon topilmadi'});return True
        response={'listing':listing_detail(con,row,item,data)}
    con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',(actor,'admin-'+kind+'-read',uid+(':'+service if service else ''),datetime.now(timezone.utc).isoformat()))
    con.commit()
    handler.reply(200,response)
    return True
