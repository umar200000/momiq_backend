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
    missing=[]
    if not profile.get('first') or not profile.get('last'): missing.append('ism va familiya')
    if not profile.get('photo'): missing.append('profil rasmi')
    if type(sitter.get('years')) is not int: missing.append('tajriba')
    if not str(sitter.get('about','')).strip(): missing.append('tavsif')
    if item['type']!='homeVisit' and not sitter.get('homePhotos'): missing.append('uy rasmi')
    return missing


def review(con,uid,kind,data,actor,environment):
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
        'homePhotos':[public_photo(p) for p in account['sitterProfile']['homePhotos']]}) if decision=='approve' else None
    con.execute('INSERT INTO listing_moderation(user_id,service,status,approved_hash,test_only,reason,reviewed_by,reviewed_at,public_media) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,service) DO UPDATE SET status=excluded.status,approved_hash=excluded.approved_hash,test_only=excluded.test_only,reason=excluded.reason,reviewed_by=excluded.reviewed_by,reviewed_at=excluded.reviewed_at,public_media=excluded.public_media',
                (uid,kind,status,digest,int(test_only),reason.strip(),actor,now(),media))
    con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',(actor,'listing-'+decision,json.dumps({'id':uid+':'+kind,'revision':revision(con,uid),'reason':reason.strip(),'testOnly':test_only}),now()))
    notifications.publish(con,uid,'listing-review:'+uid+':'+kind+':'+str(revision(con,uid)), 'listing',kind,status,reason.strip())
    con.commit()
    return document(con,uid)


def profiles(con,environment,*,interval=None):
    result=[]
    rows=con.execute("SELECT u.id,u.account,l.data FROM users u JOIN listings l ON l.user_id=u.id JOIN wallet_accounts w ON w.user_id=u.id WHERE u.blocked=0 AND w.balance_minor>=? AND EXISTS(SELECT 1 FROM user_roles r WHERE r.user_id=u.id AND r.role='sitter') ORDER BY u.id",(MINIMUM_BALANCE_MINOR,)).fetchall()
    for row in rows:
        account=json.loads(row['account']);data=json.loads(row['data'])
        if interval and sitter_availability.reason(account,*interval): continue
        profile=account.get('profile') or {};sitter=account.get('sitterProfile') or {}
        for item in data['listings']:
            moderation=con.execute("SELECT * FROM listing_moderation WHERE user_id=? AND service=? AND status='approved'",(row['id'],item['type'])).fetchone()
            if not item['active'] or not moderation or moderation['approved_hash']!=fingerprint(account,data['housing'],item): continue
            if environment=='production' or not moderation['test_only']: continue
            media=json.loads(moderation['public_media'])
            location=item.get('location')
            # Only an approximate discovery point; never expose the private street.
            public_location=({'lat':round(location['lat'],2),'lon':round(location['lon'],2),'address':'Toshkent'} if location else None)
            import booking_reviews
            reputation=booking_reviews.summary(con,row['id'],item['type'])
            result.append({'id':row['id']+':'+item['type'],'userId':row['id'],
                'name':(profile.get('first','')+' '+profile.get('last','')[:1]+'.').strip(),
                'service':SERVICES.index(item['type']),'price':item['price'],'priceUnit':'animal_day',
                'pets':[PET_LABELS[p] for p in item['pets']],
                'capacity':1 if item['type']=='personal' else item.get('capacity'),
                'rating':reputation['rating'],'reviews':reputation['count'],'years':sitter.get('years',0),'about':sitter.get('about',''),
                'photo':media['photo'],'homePhotos':media['homePhotos'],
                'location':public_location,'testOnly':True,'identityVerified':False,
                'availabilityKnown':False,'availability':sitter_availability.public(account),
                'bookingEnabled':environment in ('local','test')})
    return result


def known_names(con):
    # Archived/unavailable contacts remain valid references for existing data.
    names={r['id']:json.loads(r['profile']).get('name','') for r in con.execute('SELECT id,profile FROM sitters')}
    for row in con.execute('SELECT m.user_id,m.service,u.account FROM listing_moderation m JOIN users u ON u.id=m.user_id'):
        profile=json.loads(row['account']).get('profile',{})
        names[row['user_id']+':'+row['service']]=(profile.get('first','')+' '+profile.get('last','')).strip()
    for row in con.execute('SELECT l.user_id,l.data,u.account FROM listings l JOIN users u ON u.id=l.user_id'):
        profile=json.loads(row['account']).get('profile',{})
        for item in json.loads(row['data'])['listings']:
            names[row['user_id']+':'+item['type']]=(profile.get('first','')+' '+profile.get('last','')).strip()
    return names
