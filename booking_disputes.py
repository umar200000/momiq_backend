"""Explicit dispute adjudication; internal commission compensation only."""
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import booking_engine as engine
import booking_rules as rules
import conversations
import wallet
from support_tickets import text


def incident(con, booking, user, kind, occurred, actor, reason, excused=False):
    changed=con.execute('INSERT OR IGNORE INTO booking_incidents(booking_id,user_id,kind,occurred_at,excused) VALUES(?,?,?,?,?)',
                        (booking,user,kind,engine.stamp(occurred),int(excused))).rowcount
    if changed:
        con.execute('INSERT INTO incident_events(booking_id,user_id,revision,excused,actor,reason,created) VALUES(?,?,0,?,?,?,?)',
                    (booking,user,int(excused),actor,reason,engine.stamp(occurred)))


def late_cancel(con,row,user,current):
    if row['status']=='accepted' and rules.late_cancellation(engine.parse(row['starts_at']),current):
        incident(con,row['id'],user,'late_cancellation',current,user,'Confirmed cancellation within 24 hours')


def refundable(con,booking):
    charge=con.execute('SELECT amount_minor FROM wallet_entries WHERE source_key=?',('booking:'+booking+':commission',)).fetchone()
    refund=con.execute('SELECT amount_minor FROM wallet_entries WHERE source_key=?',('booking:'+booking+':refund',)).fetchone()
    return max(0,-(charge[0] if charge else 0)-(refund[0] if refund else 0))


def case_row(con,identity):
    return con.execute('SELECT * FROM booking_disputes WHERE booking_id=?',(identity,)).fetchone()


def public(row,current):
    if not row:return None
    return {'bookingId':row['booking_id'],'kind':row['kind'],'status':row['status'],'priorStatus':row['prior_status'],'revision':row['revision'],
            'created':row['created'],'deadline':row['deadline'],'overdue':row['status']=='open' and engine.parse(row['deadline'])<=current,
            'resolvedAt':row['resolved_at'],'outcome':row['outcome'],'reason':row['reason'],'refundMinor':row['refund_minor']}


def booking(con,identity,user,admin):
    if not admin:
        engine.account(con,user)
        return engine.owned(con,identity,user)
    row=con.execute('SELECT * FROM bookings WHERE id=?',(identity,)).fetchone()
    if not row:raise engine.BookingError(404,'Buyurtma topilmadi')
    return row


def display_name(con,user):
    row=con.execute('SELECT account FROM users WHERE id=?',(user,)).fetchone()
    profile=json.loads(row['account']).get('profile',{}) if row else {}
    return ' '.join(str(profile.get(k,'')).strip() for k in ('first','last')).strip() or user


def view(con,identity,user,current,admin=False,before=None):
    b=booking(con,identity,user,admin);row=case_row(con,identity)
    stage=rules.no_show_stage(engine.parse(b['starts_at']),current,service_started=b['status']!='accepted')
    args=[identity];clause=''
    if not admin:clause+=' AND (actor=? OR role=\'admin\')';args.append(user)
    if before:clause+=' AND id<?';args.append(before)
    messages=con.execute('SELECT * FROM dispute_events WHERE booking_id=?'+clause+' ORDER BY id DESC LIMIT 21',args).fetchall()
    result={'case':public(row,current),'bookingId':identity,'bookingStatus':b['status'],'bookingRevision':b['revision'],
            'serverNow':engine.stamp(current),'stage':stage,'canReportNoShow':row is None and stage=='complaint_available',
            'canReportService':row is None and b['status']=='active','canAddEvidence':bool(row and row['status']=='open'),
            'refundableMinor':refundable(con,identity),'customerServicePaymentRefunded':False,
            'items':[{'id':str(m['id']),'revision':m['revision'],'mine':m['actor']==user,'role':m['role'],'action':m['action'],
                      'text':m['text'],'hasImage':bool(m['image']),'created':m['created']} for m in reversed(messages[:20])],
            'nextCursor':str(messages[19]['id']) if len(messages)>20 else None}
    if admin:
        confirmations=[{'role':'customer' if e['actor']==b['customer_id'] else 'sitter','action':e['action'],'created':e['created']}
                       for e in con.execute("SELECT actor,action,created FROM booking_events WHERE booking_id=? AND action IN ('start','complete') ORDER BY revision",(identity,))]
        result.update(customerId=b['customer_id'],sitterId=b['sitter_id'],customerName=display_name(con,b['customer_id']),sitterName=display_name(con,b['sitter_id']),reporter=row['reporter'] if row else None,handoverConfirmations=confirmations)
    return result


def fields(data,expected):
    if not isinstance(data,dict) or set(data)!=set(expected):raise ValueError('Invalid dispute fields')
    if type(data.get('revision')) is not int or data['revision']<0:raise ValueError('Revision required')


def retry(con,actor,key,payload,identity):
    fingerprint=engine.retry_key(key,{'bookingId':identity,**payload})
    old=con.execute('SELECT fingerprint FROM dispute_requests WHERE actor=? AND request_id=?',(actor,key)).fetchone()
    if old and old['fingerprint']!=fingerprint:raise engine.BookingError(409,'Request ID boshqa amal uchun ishlatilgan')
    return fingerprint,bool(old)


def remember(con,actor,key,fingerprint,identity):
    con.execute('INSERT INTO dispute_requests VALUES(?,?,?,?)',(actor,key,fingerprint,identity))


def append(con,row,user,role,action,body,image,current):
    con.execute('INSERT INTO dispute_events(booking_id,revision,actor,role,action,text,image,created) VALUES(?,?,?,?,?,?,?,?)',
                (row['booking_id'],row['revision'],user,role,action,body,image,engine.stamp(current)))
    con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',
                (user,'dispute-'+action,engine.encode({'bookingId':row['booking_id'],'revision':row['revision']}),engine.stamp(current)))


def write(con,identity,user,data,photo,current,environment):
    fields(data,{'action','kind','revision','bookingRevision','text','image','requestId'})
    if data['action'] not in ('report','evidence'):raise ValueError('Invalid dispute action')
    if data['kind'] not in ('no_show','service'):raise ValueError('Invalid dispute kind')
    if type(data['bookingRevision']) is not int or data['bookingRevision']<0:raise ValueError('Booking revision required')
    body=text(data['text'],4000,True);image=photo(data['image']) if data['image'] is not None else None
    engine.begin(con);engine.test_gate(con,environment)
    b=booking(con,identity,user,False);key='owner:'+user
    fingerprint,old=retry(con,key,data['requestId'],data,identity)
    if old:return view(con,identity,user,current)
    row=case_row(con,identity)
    if b['revision']!=data['bookingRevision']:raise engine.BookingError(409,'Buyurtma o‘zgargan; yangilang')
    conversations.quota(con,key,'dispute',10)
    if data['action']=='report':
        if row or data['revision']!=0:raise engine.BookingError(409,'Nizo allaqachon ochilgan; yangilang')
        allowed=(b['status']=='accepted' and rules.no_show_stage(engine.parse(b['starts_at']),current,service_started=False)=='complaint_available') if data['kind']=='no_show' else b['status']=='active'
        if not allowed:raise engine.BookingError(409,'Bu holat yoki vaqtda nizo ochib bo‘lmaydi')
        con.execute("INSERT INTO booking_disputes(booking_id,kind,reporter,prior_status,status,revision,created,deadline) VALUES(?,?,?,?,'open',1,?,?)",
                    (identity,data['kind'],user,b['status'],engine.stamp(current),engine.stamp(rules.no_show_review_deadline(current))))
        # Private evidence is never copied into the shared booking event or notice.
        engine.change(con,b,'disputed',user,'dispute','Nizo admin ko‘rigida',current)
    else:
        if not row or row['status']!='open' or row['revision']!=data['revision'] or row['kind']!=data['kind']:raise engine.BookingError(409,'Nizo o‘zgargan yoki yopilgan')
        con.execute('UPDATE booking_disputes SET revision=revision+1 WHERE booking_id=?',(identity,))
    row=case_row(con,identity)
    append(con,row,user,'customer' if user==b['customer_id'] else 'sitter',data['action'],body,image,current)
    remember(con,key,data['requestId'],fingerprint,identity)
    return view(con,identity,user,current)


def resolve(con,identity,admin,data,current,environment):
    fields(data,{'revision','bookingRevision','requestId','outcome','reason','fault','emergency','refundMinor'})
    reason=text(data['reason'],1000,True)
    if data['outcome'] not in ('not_started','continue','cancel_service') or data['fault'] not in ('none','customer','sitter'):raise ValueError('Invalid decision')
    if type(data['emergency']) is not bool or type(data['refundMinor']) is not int or data['refundMinor']<0:raise ValueError('Invalid compensation')
    if type(data['bookingRevision']) is not int:raise ValueError('Booking revision required')
    engine.begin(con);engine.test_gate(con,environment)
    b=booking(con,identity,admin,True);key='admin:'+admin
    fingerprint,old=retry(con,key,data['requestId'],{'action':'resolve',**data},identity)
    if old:return view(con,identity,admin,current,True)
    row=case_row(con,identity)
    if not row or row['status']!='open' or row['revision']!=data['revision'] or b['revision']!=data['bookingRevision'] or b['status']!='disputed':raise engine.BookingError(409,'Nizo yoki buyurtma o‘zgargan')
    available=refundable(con,identity);refund=data['refundMinor'];outcome=data['outcome']
    if refund>available:raise ValueError('Qaytim yechilgan komissiyadan oshmaydi')
    if outcome=='not_started':
        if refund!=available:raise ValueError('Xizmat boshlanmagan bo‘lsa komissiya to‘liq tiklanadi')
        if row['kind']!='no_show' and (data['fault']!='none' or data['emergency']):raise ValueError('Kelmaslik hodisasi faqat tegishli nizoda belgilanadi')
        status='cancelled'
    elif outcome=='continue':
        if refund or data['fault']!='none' or data['emergency']:raise ValueError('Davom etishda qaytim yoki ayblov bo‘lmaydi')
        status=row['prior_status']
    else:
        if row['kind']!='service' or data['fault']!='none' or data['emergency']:raise ValueError('Bu faqat xizmat nizosi qarori')
        status='cancelled'
    if refund:
        wallet.post_entry(con,b['sitter_id'],refund,'commission_refund','booking:'+identity+':refund',admin,reason)
    if outcome=='not_started' and row['kind']=='no_show' and data['fault']!='none':
        incident(con,identity,b[data['fault']+'_id'],'no_show',engine.parse(b['starts_at']),admin,reason,data['emergency'])
    con.execute("UPDATE booking_disputes SET status='resolved',revision=revision+1,resolved_at=?,outcome=?,reason=?,refund_minor=? WHERE booking_id=?",
                (engine.stamp(current),outcome,reason,refund,identity))
    append(con,case_row(con,identity),admin,'admin','resolve',reason,None,current)
    engine.change(con,b,status,admin,'resolve_dispute','Nizo bo‘yicha admin qarori; tafsilotni oching',current)
    remember(con,key,data['requestId'],fingerprint,identity)
    return view(con,identity,admin,current,True)


def review_count(con,user,current):
    # Coarse indexed selection, then exact UTC comparison (ISO fractional
    # precision varies in historical rows and must not alter the boundary).
    rows=con.execute('SELECT booking_id,occurred_at FROM booking_incidents WHERE user_id=? AND excused=0 AND occurred_at>=? AND occurred_at<=?',
                     (user,engine.stamp(current-timedelta(days=31)),engine.stamp(current+timedelta(days=1)))).fetchall()
    return len({r['booking_id'] for r in rows if current-timedelta(days=30)<=engine.parse(r['occurred_at'])<=current})


def excuse(con,identity,user,admin,data,current):
    fields(data,{'revision','requestId','excused','reason'})
    if type(data['excused']) is not bool:raise ValueError('Explicit emergency decision required')
    reason=text(data['reason'],1000,True);engine.begin(con)
    row=con.execute('SELECT * FROM booking_incidents WHERE booking_id=? AND user_id=?',(identity,user)).fetchone()
    if not row:raise engine.BookingError(404,'Hodisa topilmadi')
    key='admin:'+admin;fingerprint,old=retry(con,key,data['requestId'],{'action':'excuse','userId':user,**data},identity)
    if not old:
        if row['revision']!=data['revision']:raise engine.BookingError(409,'Hodisa o‘zgargan')
        con.execute('UPDATE booking_incidents SET excused=?,revision=revision+1 WHERE booking_id=? AND user_id=?',(int(data['excused']),identity,user))
        con.execute('INSERT INTO incident_events(booking_id,user_id,revision,excused,actor,reason,created) VALUES(?,?,?,?,?,?,?)',
                    (identity,user,row['revision']+1,int(data['excused']),admin,reason,engine.stamp(current)))
        con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',(admin,'incident-emergency',engine.encode({'bookingId':identity,'userId':user}),engine.stamp(current)))
        remember(con,key,data['requestId'],fingerprint,identity)
    count=review_count(con,user,current)
    return {'incident':dict(con.execute('SELECT * FROM booking_incidents WHERE booking_id=? AND user_id=?',(identity,user)).fetchone()),'count30Days':count,'reviewRequired':count>=3}


def query(handler,allowed):
    values=parse_qs(urlparse(handler.path).query,keep_blank_values=True)
    if set(values)-set(allowed) or any(len(v)!=1 for v in values.values()):raise ValueError('Invalid query')
    before=values.get('before',[None])[0]
    if before is not None and not re.fullmatch(r'[1-9][0-9]{0,17}',before):raise ValueError('Invalid cursor')
    return before,values.get('status',[None])[0]


def audit_view(con,user,action,target,current):
    con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',
                (user,action,engine.encode(target),engine.stamp(current)))


def route(handler,con,user,path,photo,environment):
    owner=re.fullmatch(r'/api/bookings/([a-f0-9]{32})/dispute(?:/evidence/([1-9][0-9]{0,17})/image)?',path)
    admin=re.fullmatch(r'/api/admin/disputes(?:/([a-f0-9]{32})(?:/(resolve|evidence/([1-9][0-9]{0,17})/image))?)?',path)
    incidents=re.fullmatch(r'/api/admin/incidents(?:/([a-f0-9]{32})/([^/]+)(?:/(history|excuse))?)?',path)
    if not(owner or admin or incidents):return False
    if handler.command=='POST' and urlparse(handler.path).query:raise ValueError('Unexpected query')
    engine.test_gate(con,environment);current=datetime.now(timezone.utc)
    if incidents:
        if incidents[3]=='excuse' and handler.command=='POST':
            result=excuse(con,incidents[1],incidents[2],user,handler.body(),current);con.commit();handler.reply(200,result);return True
        if handler.command!='GET':raise engine.BookingError(404,'Topilmadi')
        before,_=query(handler,{'before'});con.execute('BEGIN')
        if incidents[3]=='history':
            rows=con.execute('SELECT * FROM incident_events WHERE booking_id=? AND user_id=?'+(' AND id<?' if before else '')+' ORDER BY id DESC LIMIT 21',
                             [incidents[1],incidents[2]]+([int(before)] if before else [])).fetchall()
            result={'items':[dict(r) for r in rows[:20]],'nextCursor':str(rows[19]['id']) if len(rows)>20 else None}
        elif incidents[1]:raise engine.BookingError(404,'Topilmadi')
        else:
            rows=con.execute('SELECT * FROM booking_incidents'+(' WHERE seq<?' if before else '')+' ORDER BY seq DESC LIMIT 21',([int(before)] if before else [])).fetchall()
            result={'items':[{**dict(r),'name':display_name(con,r['user_id']),'count30Days':review_count(con,r['user_id'],current),'reviewRequired':review_count(con,r['user_id'],current)>=3} for r in rows[:20]],'nextCursor':str(rows[19]['seq']) if len(rows)>20 else None}
        audit_view(con,user,'incident-history-view' if incidents[3]=='history' else 'incident-list-view',
                   {'bookingId':incidents[1],'userId':incidents[2],'before':int(before) if before else None},current)
        con.commit();handler.reply(200,result);return True
    identity=owner[1] if owner else admin[1];is_admin=bool(admin)
    image=owner[2] if owner else admin[3]
    if handler.command=='GET':
        if admin and admin[2]=='resolve':raise engine.BookingError(404,'Topilmadi')
        before,status=query(handler,{'before','status'} if not identity else {'before'});con.execute('BEGIN')
        if image:
            if before:raise ValueError('Image has no cursor')
            booking(con,identity,user,is_admin)
            row=con.execute('SELECT * FROM dispute_events WHERE booking_id=? AND id=?',(identity,int(image))).fetchone()
            if not row or not row['image'] or (not is_admin and row['actor']!=user):raise engine.BookingError(404,'Dalil topilmadi')
            if is_admin:
                con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',(user,'dispute-image-view',identity+':'+image,engine.stamp(current)));con.commit()
            result={'image':row['image']}
        elif identity:result=view(con,identity,user,current,is_admin,before)
        else:
            if status not in (None,'open','resolved'):raise ValueError('Invalid status')
            clauses=[];args=[]
            if before:clauses.append('seq<?');args.append(int(before))
            if status:clauses.append('status=?');args.append(status)
            rows=con.execute('SELECT * FROM booking_disputes'+(' WHERE '+' AND '.join(clauses) if clauses else '')+' ORDER BY seq DESC LIMIT 21',args).fetchall()
            result={'items':[public(r,current) for r in rows[:20]],'nextCursor':str(rows[19]['seq']) if len(rows)>20 else None}
        if is_admin and not image:
            audit_view(con,user,'dispute-detail-view' if identity else 'dispute-list-view',
                       {'bookingId':identity,'before':int(before) if before else None,'status':status},current)
            con.commit()
        handler.reply(200,result);return True
    if handler.command=='POST' and identity and not image:
        if owner:result=write(con,identity,user,handler.body(),photo,current,environment)
        elif admin[2]=='resolve':result=resolve(con,identity,user,handler.body(),current,environment)
        else:raise engine.BookingError(404,'Topilmadi')
        con.commit();handler.reply(200,result);return True
    raise engine.BookingError(404,'Topilmadi')
