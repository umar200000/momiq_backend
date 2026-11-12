"""Administrator-owned, versioned legal DRAFTS; not published consent terms."""
import json
from datetime import datetime, timezone
from pathlib import Path
import re
from urllib.parse import urlparse, parse_qs
from booking_engine import BookingError

ORGANIZATION=('legalName','registration','address','supportEmail','supportPhone','website')
DOCUMENTS=('terms','privacy','cancellation','community','deletion')
SUPPORT={'timezone':'Asia/Tashkent','weekdays':[1,2,3,4,5,6],'opens':'09:00','closes':'18:00','reviewBusinessDays':3}


def defaults():
    return json.loads((Path(__file__).with_name('legal_drafts.json')).read_text(encoding='utf-8'))


def view(row=None):
    return {'version':row['version'] if row else 0,'status':'draft',
            **(json.loads(row['payload']) if row else defaults()),
            'updatedAt':row['created'] if row else None,'supportSchedule':SUPPORT}


def current(con):
    return view(con.execute('SELECT * FROM legal_document_versions ORDER BY version DESC LIMIT 1').fetchone())


def clean(data):
    if not isinstance(data,dict) or set(data)!={'version','organization','documents','reason'}:
        raise ValueError('Hujjat maydonlari noto‘g‘ri')
    if type(data['version']) is not int or not 0<=data['version']<2**53-1:
        raise ValueError('Hujjat versiyasi kerak')
    for group,keys,limit,required in [('organization',ORGANIZATION,500,False),('documents',DOCUMENTS,40000,True)]:
        values=data[group]
        if not isinstance(values,dict) or set(values)!=set(keys):raise ValueError('Hujjat tarkibi noto‘g‘ri')
        for value in values.values():
            if not isinstance(value,str) or len(value)>limit or (required and not value.strip()) or '\x00' in value:
                raise ValueError('Matn bo‘sh yoki juda uzun')
    reason=data['reason']
    if not isinstance(reason,str) or not reason.strip() or len(reason)>1000:raise ValueError('Tahrir sababi kerak')
    return {key:{k:v.strip() for k,v in data[key].items()} for key in ('organization','documents')}


def route(handler,con,actor,path):
    if not path.startswith('/api/admin/legal-documents'):return False
    if getattr(handler,'operator_role',None)!='administrator':raise BookingError(403,'Faqat administrator uchun')
    query=parse_qs(urlparse(handler.path).query,keep_blank_values=True)
    stamp=datetime.now(timezone.utc).isoformat()
    if path=='/api/admin/legal-documents' and handler.command in ('GET','PUT'):
        if query:raise ValueError('Ortiqcha so‘rov parametri')
        data=handler.body() if handler.command=='PUT' else None
        payload=clean(data) if data is not None else None
        con.execute('BEGIN IMMEDIATE')
        old=current(con)
        if data is not None:
            if data['version']!=old['version']:raise BookingError(409,'Hujjatlar o‘zgargan; qoralamangizni saqlab, yangi versiyani oching')
            version=old['version']+1
            con.execute('INSERT INTO legal_document_versions VALUES(?,?,?,?,?)',
                        (version,json.dumps(payload,ensure_ascii=False),actor,data['reason'].strip(),stamp))
            result=current(con)
            action='legal-draft-save'
        else:result=old;action='legal-draft-view'
        con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',
                    (actor,action,json.dumps({'version':result['version']}),stamp))
        con.commit();handler.reply(200,result);return True
    if path=='/api/admin/legal-documents/history' and handler.command=='GET':
        if set(query)-{'before'} or any(len(v)!=1 for v in query.values()):raise ValueError('Tarix filtri noto‘g‘ri')
        before=query.get('before',[None])[0]
        if before is not None and not re.fullmatch(r'[1-9][0-9]{0,14}',before):raise ValueError('Tarix versiyasi noto‘g‘ri')
        con.execute('BEGIN IMMEDIATE')
        rows=con.execute('SELECT version,actor,reason,created FROM legal_document_versions'+(' WHERE version<?' if before else '')+' ORDER BY version DESC LIMIT 21',(int(before),) if before else ()).fetchall()
        result={'items':[dict(r) for r in rows[:20]],'nextCursor':str(rows[19]['version']) if len(rows)>20 else None}
        con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',(actor,'legal-history-view',json.dumps({'before':before}),stamp))
        con.commit();handler.reply(200,result);return True
    raise BookingError(404,'Hujjat yo‘li topilmadi')
