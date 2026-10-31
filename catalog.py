"""Listing moderation and derived discovery; no client-owned approval flags."""
import hashlib
import json
import notifications
import sitter_availability
from datetime import datetime, timezone
from wallet import MINIMUM_BALANCE_MINOR
from media_validation import public_photo

SERVICES=('boarding','homeVisit','personal')
PET_LABELS={'cat':'Mushuk','dog':'It'}


class CatalogError(Exception):
    def __init__(self,status,message):
        self.status,self.message=status,message


def now():
    return datetime.now(timezone.utc).isoformat()


def public_inputs(account):
    # Changes to private pets, notifications or language do not invalidate review.
    return {'profile':account.get('profile',{}),'sitterProfile':account.get('sitterProfile')}


def fingerprint(account,housing,item):
    value={'account':public_inputs(account),'housing':housing,
           'listing':{k:v for k,v in item.items() if k!='active'}}
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def revision(con,uid):
    row=con.execute('SELECT revision FROM listing_revisions WHERE user_id=?',(uid,)).fetchone()
    return row[0] if row else 0


def claim(con,uid,expected):
    if expected is None: raise CatalogError(428,'E’lonlarni qayta yuklang; ilovani yangilang.')
    if type(expected) is not int or expected<0: raise ValueError('Invalid listing revision')
    con.execute('INSERT OR IGNORE INTO listing_revisions(user_id) VALUES(?)',(uid,))
    if not con.execute('UPDATE listing_revisions SET revision=revision+1 WHERE user_id=? AND revision=?',(uid,expected)).rowcount:
        raise CatalogError(409,'E’lon boshqa qurilmada yoki admin tomonidan o‘zgargan. Qayta yuklang.')


def account_for(con,uid):
    row=con.execute('SELECT account,blocked FROM users WHERE id=?',(uid,)).fetchone()
    if not row: raise CatalogError(404,'Enaga topilmadi')
    return json.loads(row['account']),bool(row['blocked'])


def document(con,uid):
    if not con.in_transaction: con.execute('BEGIN')
    account,_=account_for(con,uid)
    row=con.execute('SELECT data FROM listings WHERE user_id=?',(uid,)).fetchone()
    data=json.loads(row[0]) if row else {'housing':(account.get('sitterProfile') or {}).get('housing','apartment'),'listings':[]}
    states={}
    for item in data['listings']:
        row=con.execute('SELECT * FROM listing_moderation WHERE user_id=? AND service=?',(uid,item['type'])).fetchone()
        status=row['status'] if row else ('pending' if item['active'] else 'draft')
        if status=='approved' and row['approved_hash']!=fingerprint(account,data['housing'],item): status='pending'
        states[item['type']]={'status':status,'reason':row['reason'] if row else '',
                              'testOnly':bool(row['test_only']) if row else False}
        if row and status in ('rejected','suspended') and row['reason'] and row['reviewed_by']:
            states[item['type']]['appealTarget']={'kind':'listing','id':uid+':'+item['type'],
                                                  'purpose':'appeal','revision':str(revision(con,uid))}
    return dict(data,_revision=revision(con,uid),moderation=states)


def save(con,uid,data,expected):
    con.execute('BEGIN IMMEDIATE')
    account,blocked=account_for(con,uid)
    if blocked or not account.get('sitterProfile'): raise CatalogError(403,'Avval enaga profilini to‘ldiring')
    protect_commitments(con,uid,data)
    claim(con,uid,expected)
    existing={r['service']:r for r in con.execute('SELECT * FROM listing_moderation WHERE user_id=?',(uid,))}
    present=set()
    for item in data['listings']:
        kind=item['type'];present.add(kind);old=existing.get(kind)
        unchanged=old and old['approved_hash']==fingerprint(account,data['housing'],item)
        reusable=unchanged and old['status'] in ('approved','suspended')
        status=('approved' if reusable else 'pending') if item['active'] else ('suspended' if reusable else 'draft')
        con.execute("INSERT INTO listing_moderation(user_id,service,status) VALUES(?,?,?) ON CONFLICT(user_id,service) DO UPDATE SET status=excluded.status,reason=''",(uid,kind,status))
    for kind in set(existing)-present:
        con.execute("UPDATE listing_moderation SET status='archived' WHERE user_id=? AND service=?",(uid,kind))
    con.execute('INSERT INTO listings VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET data=excluded.data,updated=excluded.updated',(uid,json.dumps(data),now()))
    con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',(uid,'listings-save',uid+':'+str(revision(con,uid)),now()))
    con.commit()
    return document(con,uid)


def outstanding_care(con,uid):
    return con.execute("SELECT b.*,COUNT(a.animal_id) animal_count FROM bookings b JOIN booking_animals a ON a.booking_id=b.id WHERE b.sitter_id=? AND b.status IN ('accepted','active','disputed') GROUP BY b.id",(uid,)).fetchall()


def protect_commitments(con,uid,data):
    """Listing edits share the acceptance write lock; old obligations survive pause/archive."""
    obligations=outstanding_care(con,uid)
    if not obligations:return
    old=con.execute('SELECT data FROM listings WHERE user_id=?',(uid,)).fetchone()
    old=json.loads(old[0]) if old else {}
    residential=any(b['service']!='homeVisit' for b in obligations)
    if residential and old.get('housing')!=data['housing']:
        raise CatalogError(409,'Qabul qilingan parvarish tugamaguncha uy turini o‘zgartirib bo‘lmaydi')
    for item in data['listings']:
        related=[b for b in obligations if b['service']==item['type']]
        if not related:continue
        if item['type']!='homeVisit':
            # Compare with each agreement, including an archived/re-added listing.
            for booking in related:
                snapshot=json.loads(con.execute('SELECT snapshot FROM booking_quotes WHERE id=?',(booking['quote_id'],)).fetchone()[0])
                if item.get('location')!=snapshot['address']:
                    raise CatalogError(409,'Qabul qilingan buyurtmaning parvarish manzili o‘zgarmaydi; avval mavjud majburiyatni yakunlang')
        if item['type']=='boarding':
            sweep=[]
            for b in related:sweep.extend([(b['starts_at'],b['animal_count']),(b['ends_at'],-b['animal_count'])])
            occupancy=0
            for _,delta in sorted(sweep,key=lambda v:(v[0],v[1])):
                occupancy+=delta
                if occupancy>item['capacity']:
                    raise CatalogError(409,'Sig‘im qabul qilingan buyurtmalardagi hayvonlar sonidan kamaymasin')


def invalidate_profile(con,uid,before,after):
    old_sitter=before.get('sitterProfile') or {};new_sitter=after.get('sitterProfile') or {}
    if old_sitter.get('housing')!=new_sitter.get('housing') or (old_sitter and not new_sitter):
        obligations=outstanding_care(con,uid)
        if obligations and (not new_sitter or any(b['service']!='homeVisit' for b in obligations)):
            raise CatalogError(409,'Qabul qilingan parvarish davomida enaga profili yoki uy turini almashtirib bo‘lmaydi')
    if public_inputs(before)==public_inputs(after): return
    def reviewed_fields(value):
        result = public_inputs(value)
        if result['sitterProfile'] is not None:
            result['sitterProfile'] = {k:v for k,v in result['sitterProfile'].items()
                                      if k not in ('schedule','closedDates')}
        return result
    if reviewed_fields(before)==reviewed_fields(after):
        # Keep the existing hash format (no migration/reapproval of all users).
        # Rebase only a still-valid approval, never revive a stale/rejected one.
        raw = con.execute('SELECT data FROM listings WHERE user_id=?',(uid,)).fetchone()
        if raw:
            data = json.loads(raw[0])
            for item in data['listings']:
                con.execute("UPDATE listing_moderation SET approved_hash=? WHERE user_id=? AND service=? AND status IN ('approved','suspended') AND approved_hash=?",
                    (fingerprint(after,data['housing'],item),uid,item['type'],fingerprint(before,data['housing'],item)))
        return
    con.execute("UPDATE listing_moderation SET status='pending',reason='Profil o‘zgargan; qayta tekshiruv kerak' WHERE user_id=? AND status='approved'",(uid,))
    if con.execute('SELECT 1 FROM listings WHERE user_id=?',(uid,)).fetchone():
        con.execute('INSERT OR IGNORE INTO listing_revisions(user_id) VALUES(?)',(uid,))
        con.execute('UPDATE listing_revisions SET revision=revision+1 WHERE user_id=?',(uid,))


def archive(con,uid,kind,expected):
    con.execute('BEGIN IMMEDIATE')
    current=document(con,uid)
    item=next((x for x in current['listings'] if x['type']==kind),None)
    if not item: raise CatalogError(404,'E’lon topilmadi')
    claim(con,uid,expected)
    item['active']=False
    data={k:current[k] for k in ('housing','listings')}
    con.execute('UPDATE listings SET data=?,updated=? WHERE user_id=?',(json.dumps(data),now(),uid))
    con.execute("INSERT INTO listing_moderation(user_id,service,status,reason) VALUES(?,?,'archived','Egasi arxivladi') ON CONFLICT(user_id,service) DO UPDATE SET status='archived',approved_hash=NULL,public_media=NULL,reason='Egasi arxivladi'",(uid,kind))
    con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',(uid,'listing-archive',uid+':'+kind,now()))
    con.commit()
    return document(con,uid)


def completeness(account,item):
    profile=account.get('profile') or {};sitter=account.get('sitterProfile') or {}
    if not isinstance(profile,dict) or not isinstance(sitter,dict): return ['profil formati']
    missing=[]
    if any(not isinstance(profile.get(key),str) or not profile[key].strip() or len(profile[key])>100 for key in ('first','last')):
        missing.append('ism va familiya')
    if not profile.get('photo'): missing.append('profil rasmi')
    if type(sitter.get('years')) is not int or not 0<=sitter['years']<=80: missing.append('tajriba')
    about=sitter.get('about')
    if not isinstance(about,str) or not about.strip() or len(about)>4000: missing.append('tavsif')
    homes=sitter.get('homePhotos',[])
    if (not isinstance(homes,list) or len(homes)>9 or any(not isinstance(photo,str) or not photo for photo in homes)
            or (item['type']!='homeVisit' and not homes)): missing.append('uy rasmi')
    if sitter.get('housing','apartment') not in ('apartment','house'):missing.append('uy turi')
    return missing


def review(con,uid,kind,data,actor,environment):
    if set(data)-{'decision','reason','testOnly','_revision'}:raise ValueError('Unexpected moderation fields')
    decision=data.get('decision');reason=data.get('reason')
    if decision not in ('approve','reject','suspend'): raise ValueError('Invalid review decision')
    if not isinstance(reason,str) or not reason.strip() or len(reason)>1000: raise ValueError('Review reason required')
    test_only=data.get('testOnly',False)
    if type(test_only) is not bool: raise ValueError('Invalid test flag')
    con.execute('BEGIN IMMEDIATE')
    account,blocked=account_for(con,uid)
    current=document(con,uid)
    item=next((x for x in current['listings'] if x['type']==kind),None)
    if not item: raise CatalogError(404,'E’lon topilmadi')
    if decision=='approve':
        if blocked or not item['active']: raise CatalogError(409,'Bloklangan yoki nofaol e’lon tasdiqlanmaydi')
        missing=completeness(account,item)
        if missing: raise CatalogError(409,'Profilni to‘ldiring: '+', '.join(missing))
        # MyID is intentionally deferred. Never label a manual/test approval verified.
        if environment=='production' or not test_only:
            raise CatalogError(409,'MyID integratsiyasi hali tayyor emas. Faqat test muhitida test e’lon tasdiqlanadi.')
    claim(con,uid,data.get('_revision'))
    status={'approve':'approved','reject':'rejected','suspend':'suspended'}[decision]
    digest=fingerprint(account,current['housing'],item) if decision=='approve' else None
    media = json.dumps({'photo':public_photo(account['profile']['photo']),
        'homePhotos':[public_photo(p) for p in (account['sitterProfile'].get('homePhotos') or [])]}) if decision=='approve' else None
    con.execute('INSERT INTO listing_moderation(user_id,service,status,approved_hash,test_only,reason,reviewed_by,reviewed_at,public_media) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,service) DO UPDATE SET status=excluded.status,approved_hash=excluded.approved_hash,test_only=excluded.test_only,reason=excluded.reason,reviewed_by=excluded.reviewed_by,reviewed_at=excluded.reviewed_at,public_media=excluded.public_media',
                (uid,kind,status,digest,int(test_only),reason.strip(),actor,now(),media))
    con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',(actor,'listing-'+decision,json.dumps({'id':uid+':'+kind,'revision':revision(con,uid),'reason':reason.strip(),'testOnly':test_only}),now()))
    notifications.publish(con,uid,'listing-review:'+uid+':'+kind+':'+str(revision(con,uid)), 'listing',kind,status,reason.strip())
    con.commit()
    return document(con,uid)


def profiles(con,environment,*,interval=None):
    return list(iter_profiles(con,environment,interval=interval))


def profile(con,environment,identity,*,interval=None):
    if not isinstance(identity,str):return None
    owner,separator,service=identity.rpartition(':')
    if not separator or not owner or service not in SERVICES:return None
    return next(iter_profiles(con,environment,interval=interval,owner=owner,service=service),None)


def iter_profiles(con,environment,*,interval=None,after='',owner=None,service=None,favorites=None):
    after_key=tuple(after.split(':',1)) if after else ('','')
    owner_clause=' AND m.user_id=?' if owner is not None else ''
    service_clause=' AND m.service=?' if service is not None else ''
    args=[*after_key,MINIMUM_BALANCE_MINOR]+([owner] if owner is not None else [])+([service] if service is not None else [])
    favorite_clause = ''
    if favorites is not None:
        keys = []
        for identity in favorites:
            if not isinstance(identity, str):
                continue
            owner_id, separator, kind = identity.rpartition(':')
            if separator and owner_id and kind in SERVICES:
                keys.append((owner_id, kind))
        if not keys:
            return
        favorite_clause = (" AND (m.user_id,m.service) IN (SELECT json_extract(value,'$[0]'),"
                           "json_extract(value,'$[1]') FROM json_each(?))")
        args.append(json.dumps(keys))
    # Read in the moderation primary-key order. Reputation stays in the same
    # read snapshot without one additional Python/SQLite call per listing.
    rows=con.execute("""SELECT u.id,u.account,l.data,m.service moderated_service,
        m.approved_hash,m.public_media,m.test_only,
        (SELECT json_array(COUNT(*),COALESCE(SUM(stars),0)) FROM booking_reviews r
         WHERE r.sitter_id=m.user_id AND r.service=m.service
         AND r.hidden=0 AND r.withdrawn=0 AND r.test_only=0) review_totals
        FROM listing_moderation m JOIN users u ON u.id=m.user_id
        JOIN listings l ON l.user_id=m.user_id JOIN wallet_accounts w ON w.user_id=m.user_id
        WHERE (m.user_id,m.service)>(?,?) AND m.status='approved' AND u.blocked=0
        AND w.balance_minor>=?
        AND EXISTS(SELECT 1 FROM user_roles r WHERE r.user_id=m.user_id AND r.role='sitter')"""
        +owner_clause+service_clause+favorite_clause+' ORDER BY m.user_id,m.service',args)
    for row in rows:
        account=json.loads(row['account']);data=json.loads(row['data'])
        if interval and sitter_availability.reason(account,*interval): continue
        profile=account.get('profile') or {};sitter=account.get('sitterProfile') or {}
        for item in sorted(data['listings'],key=lambda value:value['type']):
            if item['type']!=row['moderated_service']:continue
            if (row['id'],item['type'])<=after_key:continue
            if not item['active'] or row['approved_hash']!=fingerprint(account,data['housing'],item): continue
            if environment=='production' or not row['test_only']: continue
            media=json.loads(row['public_media'])
            location=item.get('location')
            # Only an approximate discovery point; never expose the private street.
            public_location=({'lat':round(location['lat'],2),'lon':round(location['lon'],2),'address':'Toshkent'} if location else None)
            review_count,review_total=json.loads(row['review_totals'])
            reputation={'count':review_count,'rating':round(review_total/review_count,1) if review_count else 0}
            yield {'id':row['id']+':'+item['type'],'userId':row['id'],
                'name':(profile.get('first','')+' '+profile.get('last','')[:1]+'.').strip(),
                'service':SERVICES.index(item['type']),'price':item['price'],'priceUnit':'animal_day',
                'pets':[PET_LABELS[p] for p in item['pets']],
                'capacity':1 if item['type']=='personal' else item.get('capacity'),
                'rating':reputation['rating'],'reviews':reputation['count'],'years':sitter.get('years',0),'about':sitter.get('about',''),
                'photo':media['photo'],'homePhotos':media['homePhotos'],
                'location':public_location,'testOnly':True,'identityVerified':False,
                'availabilityKnown':False,'availability':sitter_availability.public(account),
                'bookingEnabled':environment in ('local','test')}


def contacts_exist(con, identities):
    # An archived listing is still a valid historical contact. Only a new
    # conversation additionally requires current discovery eligibility.
    if not all(isinstance(identity, str) for identity in identities):
        return False
    requested = []
    for identity in dict.fromkeys(identities):
        owner, _, service = identity.rpartition(':')
        requested.append([identity, owner or None, service])
    if not requested:
        return True
    unknown = con.execute("""
        WITH contacts AS (
            SELECT json_extract(value,'$[0]') AS id, json_extract(value,'$[1]') AS owner,
                   json_extract(value,'$[2]') AS service FROM json_each(?)
        )
        SELECT 1 FROM contacts c
        WHERE NOT EXISTS (SELECT 1 FROM sitters WHERE id=c.id)
          AND NOT EXISTS (SELECT 1 FROM listing_moderation WHERE user_id=c.owner AND service=c.service)
          AND NOT EXISTS (
              SELECT 1 FROM listings l, json_each(l.data,'$.listings') item
              WHERE l.user_id=c.owner AND json_extract(item.value,'$.type')=c.service
          ) LIMIT 1""", (json.dumps(requested),)).fetchone()
    return unknown is None
