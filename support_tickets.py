"""Private owner/support threads; no service, balance or dispute decision side effects."""
import json
import re
import secrets
from datetime import datetime,timezone
from urllib.parse import parse_qs,urlparse

import booking_engine as engine
import conversations
import notifications


def text(value,limit,required=False):
    if not isinstance(value,str) or len(value)>limit or any(ord(c)<32 and c not in '\n\t' for c in value):raise ValueError('Invalid support text')
    value=value.strip()
    if required and not value:raise ValueError('Text required')
    return value


def ticket(con,identity,user,admin=False):
    if not admin:engine.account(con,user)
    row=con.execute('SELECT * FROM support_tickets WHERE id=?'+('' if admin else ' AND owner_id=?'),(identity,) if admin else (identity,user)).fetchone()
    if not row:raise engine.BookingError(404,'Murojaat topilmadi')
    return row


def public(row):
    return {k:row[v] for k,v in [('id','id'),('bookingId','booking_id'),('subject','subject'),('topic','topic'),('status','status'),('revision','revision'),('created','created'),('updated','updated')]}


def cursor(handler):
    query=parse_qs(urlparse(handler.path).query,keep_blank_values=True)
    if set(query)-{'before','status'} or any(len(v)!=1 for v in query.values()):raise ValueError('Invalid support query')
    before=query.get('before',[None])[0];status=query.get('status',[None])[0]
    if before is not None and not re.fullmatch(r'[1-9][0-9]{0,17}',before):raise ValueError('Invalid support cursor')
    if status is not None and status not in ('open','waiting_user','resolved'):raise ValueError('Invalid status')
    return before,status


def view(con,identity,user,admin=False,before=None):
    row=ticket(con,identity,user,admin);args=[identity];clause=''
    if before is not None:clause=' AND id<?';args.append(int(before))
    rows=con.execute('SELECT * FROM support_messages WHERE ticket_id=?'+clause+' ORDER BY id DESC LIMIT 21',args).fetchall()
    return {'ticket':public(row),'items':[{'id':str(m['id']),'revision':m['revision'],'authorRole':m['author_role'],'action':m['action'],'text':m['text'],'hasImage':bool(m['image']),'created':m['created']} for m in reversed(rows[:20])],
            'nextCursor':str(rows[19]['id']) if len(rows)>20 else None}


def audit_detail(con,identity,user,before):
    # Only the requested record/page identity is retained, never ticket contents.
    target=engine.encode({'ticketId':identity,'before':int(before) if before else None})
    con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',
                (user,'support-view',target,datetime.now(timezone.utc).isoformat()))


def write(con,user,identity,data,validate_photo,admin=False):
    creating=identity is None
    required={'requestId','text','image','revision','action'}|({'subject','topic','bookingId'} if creating else set())
    if not isinstance(data,dict) or set(data)!=required:raise ValueError('Invalid support fields')
    action=data['action'];revision=data['revision']
    if type(revision) is not int or revision<0:raise ValueError('Revision required')
    if action not in ('reply','resolve') or (action=='resolve' and (creating or not admin)):raise ValueError('Invalid support action')
    body=text(data['text'],4000,action=='resolve')
    image=data['image']
    if image is not None:image=validate_photo(image)
    if not body and not image:raise ValueError('Message or image required')
    if creating and admin:raise ValueError('Owner creates a ticket')
    if creating:
        subject=text(data['subject'],120,True)
        topic=data['topic'];booking=data['bookingId']
        if topic not in ('general','booking','payment','account','safety'):raise ValueError('Invalid topic')
        if booking is not None and (not isinstance(booking,str) or not re.fullmatch(r'[a-f0-9]{32}',booking)):raise ValueError('Invalid booking')
        if topic=='booking' and booking is None:raise ValueError('Booking required')
    fingerprint=engine.retry_key(data['requestId'],{'ticketId':identity,**data})
    key=('admin:' if admin else 'owner:')+user
    engine.begin(con)
    if not admin:engine.account(con,user)
    if not creating:row=ticket(con,identity,user,admin)
    previous=con.execute('SELECT * FROM support_requests WHERE actor=? AND request_id=?',(key,data['requestId'])).fetchone()
    if previous:
        if previous['fingerprint']!=fingerprint:raise engine.BookingError(409,'So‘rov boshqa murojaat uchun ishlatilgan')
        return view(con,previous['ticket_id'],user,admin)
    conversations.quota(con,key,'support',30 if admin else 10)
    current=datetime.now(timezone.utc).isoformat()
    if creating:
        if revision!=0:raise engine.BookingError(409,'Yangi murojaat versiyasi 0 bo‘lsin')
        if booking:engine.owned(con,booking,user)
        identity=secrets.token_hex(16)
        con.execute('INSERT INTO support_tickets(id,owner_id,booking_id,subject,topic,status,revision,created,updated) VALUES(?,?,?,?,?,?,0,?,?)',(identity,user,booking,subject,topic,'open',current,current))
        row=ticket(con,identity,user)
    elif row['revision']!=revision:raise engine.BookingError(409,'Murojaat o‘zgargan. Yangilang')
    state='resolved' if action=='resolve' else ('waiting_user' if admin else 'open')
    con.execute('UPDATE support_tickets SET status=?,revision=revision+1,updated=? WHERE id=?',(state,current,identity))
    con.execute('INSERT INTO support_messages(ticket_id,revision,actor,author_role,action,text,image,created) VALUES(?,?,?,?,?,?,?,?)',(identity,revision+1,key,'support' if admin else 'owner',action,body,image,current))
    con.execute('INSERT INTO support_requests VALUES(?,?,?,?)',(key,data['requestId'],fingerprint,identity))
    con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',(user,'support-'+action,engine.encode({'ticketId':identity,'revision':revision+1}),current))
    if admin:notifications.publish(con,row['owner_id'],f'support:{identity}:{revision+1}','support',identity,state,'')
    return view(con,identity,user,admin)


def route(handler,con,user,path,validate_photo):
    match=re.fullmatch(r'/api/(admin/)?support(?:/([a-f0-9]{32})(?:/messages/([1-9][0-9]{0,17})/image)?)?',path)
    if not match:return False
    admin=bool(match[1]);identity=match[2];image_id=match[3]
    if not admin:engine.account(con,user)
    if handler.command=='GET':
        before,status=cursor(handler)
        if identity and status:raise ValueError('Status filter is only for lists')
        con.execute('BEGIN')
        if image_id:
            if before:raise ValueError('Image has no cursor')
            ticket(con,identity,user,admin)
            row=con.execute('SELECT image FROM support_messages WHERE id=? AND ticket_id=?',(int(image_id),identity)).fetchone()
            if not row or not row['image']:raise engine.BookingError(404,'Rasm topilmadi')
            if admin:
                con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',(user,'support-image-view',identity+':'+image_id,datetime.now(timezone.utc).isoformat()));con.commit()
            handler.reply(200,{'image':row['image']})
            return True
        if identity:
            result=view(con,identity,user,admin,before)
            if admin:
                audit_detail(con,identity,user,before)
                con.commit()
            handler.reply(200,result);return True
        clauses=[] if admin else ['owner_id=?'];args=[] if admin else [user]
        if before:clauses.append('seq<?');args.append(int(before))
        if status:clauses.append('status=?');args.append(status)
        rows=con.execute('SELECT * FROM support_tickets'+(' WHERE '+' AND '.join(clauses) if clauses else '')+' ORDER BY seq DESC LIMIT 21',args).fetchall()
        result={'items':[public(r) for r in rows[:20]],'nextCursor':str(rows[19]['seq']) if len(rows)>20 else None}
        # Historical account messages are shown as an archive, not imported as
        # trusted operator replies or assigned a fabricated delivery status.
        if not admin and not before:result['legacyItems']=engine.account(con,user).get('support',[])
        handler.reply(200,result);return True
    if handler.command=='POST' and not image_id:
        result=write(con,user,identity,handler.body(),validate_photo,admin);con.commit();handler.reply(200,result);return True
    raise engine.BookingError(404,'Topilmadi')
