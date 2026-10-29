"""One customer review per completed booking; TEST entries never affect ratings."""
import json
import re
from urllib.parse import parse_qs, urlparse, unquote

import booking_engine as engine
import conversations

def public(row):
    return {'id': str(row['id']), 'name': row['author_name'], 'stars': row['stars'],
            'text': row['text'], 'created': row['created'], 'updated': row['updated'],
            'testOnly': bool(row['test_only']), 'revision': row['revision']}


def moderation_reason(con,row):
    if not row['hidden']:return None
    event=con.execute("SELECT revision,payload,created FROM review_history WHERE review_id=? AND action='moderate' ORDER BY revision DESC LIMIT 1",(row['id'],)).fetchone()
    if not event:return None
    payload=json.loads(event['payload'])
    if not payload.get('hidden'):return None
    return {'reason':payload.get('reason',''),'revision':event['revision'],'decidedAt':event['created']}


def owner_view(con, identity, user, now):
    engine.account(con,user)
    booking=engine.owned(con,identity,user)
    row=con.execute('SELECT * FROM booking_reviews WHERE booking_id=?',(identity,)).fetchone()
    mine=booking['customer_id']==user
    decision=moderation_reason(con,row) if row and mine else None
    return {'review':dict(public(row),hidden=bool(row['hidden']),withdrawn=bool(row['withdrawn'])) if row else None,
            'canCreate':mine and not row and booking['status']=='completed',
            'canEdit':False,'canWithdraw':bool(row and mine and not row['withdrawn']),
            'canRestore':bool(row and mine and row['withdrawn']), 'reviewEditable':False,
            'moderation':decision,
            'appealTarget':{'kind':'review','id':str(row['id']),'purpose':'appeal','revision':str(row['revision'])} if decision else None}


def summary(con,sitter,service):
    row=con.execute('SELECT COUNT(*) n,COALESCE(SUM(stars),0) total FROM booking_reviews WHERE sitter_id=? AND service=? AND hidden=0 AND withdrawn=0 AND test_only=0',(sitter,service)).fetchone()
    return {'count':row['n'],'rating':round(row['total']/row['n'],1) if row['n'] else 0}


def page(con,sitter,service,environment,before=None):
    args=[sitter,service]
    clause='sitter_id=? AND service=? AND hidden=0 AND withdrawn=0'
    if environment=='production':clause+=' AND test_only=0'
    if before is not None:
        if not isinstance(before,str) or not re.fullmatch(r'[1-9][0-9]{0,17}',before):raise ValueError('Invalid review cursor')
        clause+=' AND id<?';args.append(int(before))
    rows=con.execute('SELECT * FROM booking_reviews WHERE '+clause+' ORDER BY id DESC LIMIT 21',args).fetchall()
    return {'items':[public(row) for row in rows[:20]],'nextCursor':str(rows[19]['id']) if len(rows)>20 else None,
            **summary(con,sitter,service)}


def write(con,identity,user,data,now):
    if not isinstance(data,dict) or set(data)!={'stars','text','revision','requestId','action'}:
        raise ValueError('Invalid review fields')
    stars,body,revision,action=(data[key] for key in ('stars','text','revision','action'))
    if type(stars) is not int or not 1<=stars<=5 or type(revision) is not int or revision<0:
        raise ValueError('Rating must be an integer from 1 to 5')
    if not isinstance(body,str) or len(body)>2000 or any(ord(c)<32 and c not in '\n\t' for c in body):
        raise ValueError('Invalid review text')
    if action not in ('save','withdraw','restore'):raise ValueError('Invalid review action')
    fingerprint=engine.retry_key(data['requestId'],{'booking':identity,**data})
    engine.begin(con);engine.account(con,user)
    booking=engine.owned(con,identity,user)
    if booking['customer_id']!=user or booking['sitter_id']==user:
        raise engine.BookingError(403,'Sharhni buyurtma mijozi yozadi')
    prior=con.execute('SELECT * FROM review_requests WHERE actor=? AND request_id=?',(user,data['requestId'])).fetchone()
    if prior:
        if prior['fingerprint']!=fingerprint:raise engine.BookingError(409,'So‘rov boshqa sharh uchun ishlatilgan')
        return owner_view(con,identity,user,now)
    if booking['status']!='completed':raise engine.BookingError(409,'Sharh faqat tugallangan buyurtma uchun')
    row=con.execute('SELECT * FROM booking_reviews WHERE booking_id=?',(identity,)).fetchone()
    if revision!=(row['revision'] if row else 0):raise engine.BookingError(409,'Sharh o‘zgargan. Yangilab qayta tekshiring')
    if action!='save' and not row:raise ValueError('No review to change visibility')
    if row and action=='save':
        raise engine.BookingError(409,'Yuborilgan sharh matni va yulduzi tahrirlanmaydi')
    conversations.quota(con,user,'review',10)
    current=engine.stamp(now)
    if row:
        # Withdrawal changes visibility only, never rewrites the last submitted text.
        if stars!=row['stars'] or body.strip()!=row['text']:
            raise engine.BookingError(409,'Ko‘rinishni o‘zgartirish sharhni tahrirlamaydi')
        con.execute('UPDATE booking_reviews SET withdrawn=?,revision=revision+1,updated=? WHERE id=?',
                    (int(action=='withdraw'),current,row['id']))
        review_id=row['id']
    else:
        quote=json.loads(con.execute('SELECT snapshot FROM booking_quotes WHERE id=?',(booking['quote_id'],)).fetchone()[0])
        # Missing legacy marker is treated conservatively as TEST, never genuine.
        test_only=quote.get('testOnly') is not False
        review_id=con.execute('INSERT INTO booking_reviews(booking_id,customer_id,sitter_id,service,author_name,stars,text,test_only,revision,created,updated) VALUES(?,?,?,?,?,?,?,?,1,?,?)',
                              (identity,user,booking['sitter_id'],booking['service'],quote['customerName'],stars,body.strip(),int(test_only),current,current)).lastrowid
    updated=con.execute('SELECT * FROM booking_reviews WHERE id=?',(review_id,)).fetchone()
    payload=engine.encode({'stars':updated['stars'],'text':updated['text'],'withdrawn':bool(updated['withdrawn']),'hidden':bool(updated['hidden'])})
    con.execute('INSERT INTO review_history VALUES(?,?,?,?,?,?)',(review_id,updated['revision'],user,action,payload,current))
    con.execute('INSERT INTO review_requests VALUES(?,?,?,?,?)',(user,data['requestId'],fingerprint,review_id,updated['revision']))
    con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',(user,'review-'+action,engine.encode({'reviewId':review_id,'revision':updated['revision']}),current))
    return owner_view(con,identity,user,now)


def query_cursor(handler):
    query=parse_qs(urlparse(handler.path).query,keep_blank_values=True)
    if set(query)-{'before'} or any(len(values)!=1 for values in query.values()):raise ValueError('Invalid review query')
    before=query.get('before',[None])[0]
    if before is not None and not re.fullmatch(r'[1-9][0-9]{0,17}',before):raise ValueError('Invalid review cursor')
    return before


def public_route(handler,con,path,environment):
    match=re.fullmatch(r'/api/sitters/([^/]{1,200})/reviews',path)
    if not match:return False
    if handler.command!='GET':raise engine.BookingError(404,'Topilmadi')
    before=query_cursor(handler)
    identity=unquote(match[1])
    con.execute('BEGIN')
    item=engine.catalog.profile(con,environment,identity)
    if not item:raise engine.BookingError(404,'Enaga topilmadi')
    sitter,service=identity.rsplit(':',1)
    handler.reply(200,page(con,sitter,service,environment,before))
    return True


def moderate(con,actor,identity,data,now):
    if not isinstance(data,dict) or set(data)!={'revision','requestId','hidden','reason'}:
        raise ValueError('Invalid moderation fields')
    if type(data['hidden']) is not bool or type(data['revision']) is not int:
        raise ValueError('Invalid moderation values')
    reason=data['reason']
    if not isinstance(reason,str) or not reason.strip() or len(reason)>500:raise ValueError('Reason required')
    fingerprint=engine.retry_key(data['requestId'],{'reviewId':identity,**data})
    engine.begin(con)
    row=con.execute('SELECT * FROM booking_reviews WHERE id=?',(identity,)).fetchone()
    if not row:raise engine.BookingError(404,'Sharh topilmadi')
    key='admin:'+actor
    old=con.execute('SELECT * FROM review_requests WHERE actor=? AND request_id=?',(key,data['requestId'])).fetchone()
    if old:
        if old['fingerprint']!=fingerprint:raise engine.BookingError(409,'So‘rov boshqa qaror uchun ishlatilgan')
        return {'ok':True}
    if row['revision']!=data['revision']:raise engine.BookingError(409,'Sharh o‘zgargan. Yangilang')
    current=engine.stamp(now);revision=row['revision']+1
    con.execute('UPDATE booking_reviews SET hidden=?,revision=?,updated=? WHERE id=?',(int(data['hidden']),revision,current,identity))
    payload=engine.encode({'stars':row['stars'],'text':row['text'],'withdrawn':bool(row['withdrawn']),'hidden':data['hidden'],'reason':reason.strip()})
    con.execute('INSERT INTO review_history VALUES(?,?,?,?,?,?)',(identity,revision,key,'moderate',payload,current))
    con.execute('INSERT INTO review_requests VALUES(?,?,?,?,?)',(key,data['requestId'],fingerprint,identity,revision))
    con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',(actor,'review-moderate',engine.encode({'reviewId':identity,'revision':revision,'reason':reason.strip()}),current))
    return {'ok':True}


def audit_view(con,actor,action,now,**metadata):
    con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',
                (actor,action,engine.encode(metadata),now.isoformat()))


def admin_route(handler,con,actor,path,now):
    if path=='/api/admin/reviews' and handler.command=='GET':
        before=query_cursor(handler);args=[];clause=''
        if before is not None:clause=' WHERE id<?';args.append(int(before))
        con.execute('BEGIN')
        rows=con.execute('SELECT * FROM booking_reviews'+clause+' ORDER BY id DESC LIMIT 21',args).fetchall()
        audit_view(con,actor,'review-list-view',now,before=int(before) if before else None)
        con.commit()
        handler.reply(200,{'items':[dict(public(r),bookingId=r['booking_id'],hidden=bool(r['hidden']),withdrawn=bool(r['withdrawn'])) for r in rows[:20]],'nextCursor':str(rows[19]['id']) if len(rows)>20 else None})
        return True
    match=re.fullmatch(r'/api/admin/reviews/([1-9][0-9]{0,17})(?:/(history|moderate))?',path)
    if not match:return False
    identity=int(match[1])
    if match[2]=='moderate' and handler.command=='POST':
        result=moderate(con,actor,identity,handler.body(),now);con.commit();handler.reply(200,result)
        return True
    if match[2]=='history' and handler.command=='GET':
        before=query_cursor(handler);args=[identity];clause=''
        if before is not None:clause=' AND revision<?';args.append(int(before))
        con.execute('BEGIN')
        if not con.execute('SELECT 1 FROM booking_reviews WHERE id=?',(identity,)).fetchone():raise engine.BookingError(404,'Sharh topilmadi')
        rows=con.execute('SELECT * FROM review_history WHERE review_id=?'+clause+' ORDER BY revision DESC LIMIT 21',args).fetchall()
        audit_view(con,actor,'review-history-view',now,reviewId=identity,before=int(before) if before else None)
        con.commit()
        handler.reply(200,{'items':[dict(revision=r['revision'],actor=r['actor'],action=r['action'],payload=json.loads(r['payload']),created=r['created']) for r in rows[:20]],'nextCursor':str(rows[19]['revision']) if len(rows)>20 else None})
        return True
    raise engine.BookingError(404,'Topilmadi')
