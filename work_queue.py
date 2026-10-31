"""Audited staff assignment metadata; never changes a source decision or client money."""
from datetime import datetime,timezone
import json
import re
from urllib.parse import parse_qs,urlparse,unquote

import booking_engine as engine
import conversations
import operator_access

KINDS={'support':'support','listing':'moderation','chat_report':'moderation'}
TARGETS={'support':r'[a-f0-9]{32}','listing':r'[a-f0-9]{1,64}:(?:boarding|homeVisit|personal)','chat_report':r'[1-9][0-9]{0,17}'}
SOURCES={
    'support':"SELECT id target,subject title,status,revision,(status!='resolved') active FROM support_tickets",
    'listing':"SELECT m.user_id||':'||m.service target,m.service title,m.status status,COALESCE(r.revision,0) revision,(m.status='pending') active FROM listing_moderation m LEFT JOIN listing_revisions r ON r.user_id=m.user_id",
    'chat_report':"SELECT CAST(id AS TEXT) target,'Chat #'||id title,status,revision,(status='open') active FROM chat_reports",
}


def allowed(role,kind):
    if kind not in KINDS or role not in ('administrator',KINDS.get(kind)):
        raise engine.BookingError(403,'Bu ish navbati uchun huquq yo‘q')


def query(handler,keys):
    values=parse_qs(urlparse(handler.path).query,keep_blank_values=True)
    if set(values)-set(keys) or any(len(v)!=1 for v in values.values()):raise ValueError('Invalid work queue query')
    return {k:v[0] for k,v in values.items()}


def source(con,kind,target):
    if not re.fullmatch(TARGETS[kind],target):raise ValueError('Invalid work target')
    row=con.execute('SELECT * FROM ('+SOURCES[kind]+') WHERE target=?',(target,)).fetchone()
    if not row:raise engine.BookingError(404,'Ish topilmadi')
    return dict(row)


def assignment(con,kind,target,current):
    row=con.execute('SELECT * FROM work_assignments WHERE kind=? AND target=?',(kind,target)).fetchone()
    result={'assignee':row['assignee'] if row else None,'dueAt':row['due_at'] if row else None,'revision':row['revision'] if row else 0,
            'updatedBy':row['updated_by'] if row else None,'updated':row['updated'] if row else None}
    result['assigneeActive']=bool(result['assignee'] and operator_access.role_for(con,result['assignee']) in ('administrator',KINDS[kind]))
    result['overdue']=bool(result['dueAt'] and result['dueAt']<=current.isoformat())
    return result


def event(row):
    return {'id':str(row['id']),'revision':row['revision'],'actor':row['actor'],'reason':row['reason'],'created':row['created'],
            'before':json.loads(row['before_state']),'after':json.loads(row['after_state'])}


def view(con,kind,target,current,before=None):
    item=source(con,kind,target)
    state=assignment(con,kind,target,current);state['overdue']=state['overdue'] and bool(item['active'])
    if before is not None and not re.fullmatch(r'[1-9][0-9]{0,17}',before):raise ValueError('Invalid history cursor')
    rows=con.execute('SELECT * FROM work_assignment_events WHERE kind=? AND target=?'+(' AND id<?' if before else '')+' ORDER BY id DESC LIMIT 21',
                     [kind,target]+([int(before)] if before else [])).fetchall()
    return {'kind':kind,'source':item,'assignment':state,'items':[event(r) for r in rows[:20]],'nextCursor':str(rows[19]['id']) if len(rows)>20 else None}


def page(con,actor,role,params,current):
    kind=params.get('kind');allowed(role,kind)
    selected=params.get('filter','all');after=params.get('after','')
    if selected not in ('all','mine','unassigned','overdue'):raise ValueError('Invalid work queue filter')
    if after and not re.fullmatch(TARGETS[kind],after):raise ValueError('Invalid work queue cursor')
    clause='';args=[kind,after]
    if selected=='mine':clause=' AND w.assignee=?';args.append(actor)
    elif selected=='unassigned':clause=' AND w.assignee IS NULL'
    elif selected=='overdue':clause=' AND w.due_at<=?';args.append(current.isoformat())
    rows=con.execute('SELECT s.* FROM ('+SOURCES[kind]+') s LEFT JOIN work_assignments w ON w.kind=? AND w.target=s.target WHERE s.active=1 AND s.target>?'+clause+' ORDER BY s.target LIMIT 21',args).fetchall()
    return {'kind':kind,'filter':selected,'items':[{'source':dict(r),'assignment':assignment(con,kind,r['target'],current)} for r in rows[:20]],
            'nextCursor':rows[19]['target'] if len(rows)>20 else None}


def deadline(value):
    if value is None:return None
    if not isinstance(value,str) or len(value)>64:raise ValueError('Invalid deadline')
    parsed=datetime.fromisoformat(value)
    if parsed.tzinfo is None or not 2020<=parsed.year<=2100:raise ValueError('Timezone-aware deadline required')
    return parsed.astimezone(timezone.utc).isoformat()


def can_escalate(con,actor,role,kind,item,state):
    return bool(role=='support' and kind=='support' and item['active'] and state['assignee'] in (None,actor)
                and con.execute("""SELECT 1 FROM support_targets WHERE ticket_id=? AND kind IN ('listing','review')
                                   UNION ALL SELECT 1 FROM support_video_reports WHERE ticket_id=? LIMIT 1""",
                                (item['target'],item['target'])).fetchone())


def write(con,actor,role,kind,target,data,current,escalate=False):
    allowed(role,kind)
    if escalate and (role!='support' or kind!='support'):
        raise engine.BookingError(403,'Administratorga yo‘naltirish support roli uchun')
    if not isinstance(data,dict) or set(data)!={'revision','sourceRevision','assignee','dueAt','reason','requestId'}:raise ValueError('Invalid assignment fields')
    for key in ('revision','sourceRevision'):
        if type(data[key]) is not int or data[key]<0:raise ValueError('Assignment revisions are required')
    assignee=data['assignee'];due=deadline(data['dueAt']);reason=data['reason']
    if assignee is not None and (not isinstance(assignee,str) or not assignee.strip() or len(assignee)>100):raise ValueError('Invalid operator')
    if not isinstance(reason,str) or not reason.strip() or len(reason)>1000:raise ValueError('Reason required')
    reason=reason.strip()
    fingerprint=engine.retry_key(data['requestId'],{'kind':kind,'target':target,**data,'dueAt':due,'reason':reason,**({'operation':'escalate'} if escalate else {})})
    engine.begin(con)
    item=source(con,kind,target)
    previous=con.execute('SELECT * FROM work_assignment_events WHERE actor=? AND request_id=?',(actor,data['requestId'])).fetchone()
    if previous:
        if previous['fingerprint']!=fingerprint:raise engine.BookingError(409,'So‘rov ID boshqa amal uchun ishlatilgan')
        return {'event':event(previous),'assignment':assignment(con,kind,target,current)}
    old=assignment(con,kind,target,current)
    if not item['active'] or data['sourceRevision']!=item['revision'] or data['revision']!=old['revision']:
        raise engine.BookingError(409,'Ish yoki mas’ul o‘zgargan. Navbatni yangilang')
    if escalate:
        if not can_escalate(con,actor,role,kind,item,old) or due!=old['dueAt']:
            raise engine.BookingError(409,'Faqat bo‘sh yoki o‘zingizga biriktirilgan kontent murojaatini amaldagi muddati bilan yo‘naltirish mumkin')
        if not assignee or operator_access.role_for(con,assignee)!='administrator':
            raise engine.BookingError(409,'Faol administratorni tanlang')
    elif role!='administrator' and (assignee!=actor or old['assignee'] not in (None,actor) or due!=old['dueAt']):
        raise engine.BookingError(403,'Faqat bo‘sh ishni o‘zingizga olishingiz mumkin; muddat va qayta biriktirishni administrator boshqaradi')
    if assignee is not None and operator_access.role_for(con,assignee) not in ('administrator',KINDS[kind]):
        raise engine.BookingError(409,'Operator faol emas yoki mos rolga ega emas')
    before={'assignee':old['assignee'],'dueAt':old['dueAt']};after={'assignee':assignee,'dueAt':due,**({'escalated':True} if escalate else {})}
    if before==after:raise ValueError('Assignment has not changed')
    conversations.quota(con,'admin:'+actor,'assignment',30)
    revision=old['revision']+1;stamp=current.isoformat()
    con.execute('INSERT INTO work_assignments VALUES(?,?,?,?,?,?,?) ON CONFLICT(kind,target) DO UPDATE SET assignee=excluded.assignee,due_at=excluded.due_at,revision=excluded.revision,updated_by=excluded.updated_by,updated=excluded.updated',
                (kind,target,assignee,due,revision,actor,stamp))
    cursor=con.execute('INSERT INTO work_assignment_events(kind,target,revision,actor,reason,before_state,after_state,created,request_id,fingerprint) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (kind,target,revision,actor,reason,json.dumps(before),json.dumps(after),stamp,data['requestId'],fingerprint))
    con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',
                (actor,'work-escalation' if escalate else 'work-assignment',engine.encode({'kind':kind,'target':target,'revision':revision,'before':before,'after':after,'reason':reason}),stamp))
    return {'event':event(con.execute('SELECT * FROM work_assignment_events WHERE id=?',(cursor.lastrowid,)).fetchone()),'assignment':assignment(con,kind,target,current)}


def audit_view(con,actor,action,target,current):
    con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',
                (actor,action,engine.encode(target),current.isoformat()))


def route(handler,con,actor,path):
    if not path.startswith('/api/admin/work-queue'):return False
    role=handler.operator_role;current=datetime.now(timezone.utc)
    if path=='/api/admin/work-queue' and handler.command=='GET':
        params=query(handler,('kind','filter','after'));con.execute('BEGIN')
        result=page(con,actor,role,params,current)
        audit_view(con,actor,'work-queue-view',{'kind':result['kind'],'filter':result['filter'],'after':params.get('after') or None},current)
        con.commit();handler.reply(200,result);return True
    if path=='/api/admin/work-queue/operators' and handler.command=='GET':
        params=query(handler,('kind',));kind=params.get('kind');allowed(role,kind)
        if role!='administrator':raise engine.BookingError(403,'Operator tanlash administrator uchun')
        con.execute('BEGIN')
        rows=con.execute('SELECT p.username,p.role FROM admin_permissions p JOIN admins a ON a.username=p.username WHERE p.enabled=1 AND p.role IN (?,?) ORDER BY p.username',(KINDS[kind],'administrator')).fetchall()
        result={'items':[dict(r) for r in rows]}
        audit_view(con,actor,'work-operators-view',{'kind':kind},current)
        con.commit();handler.reply(200,result);return True
    match=re.fullmatch(r'/api/admin/work-queue/(support|listing|chat_report)/([^/]{1,100})(?:/(escalate|escalation-operators))?',path)
    if not match:raise engine.BookingError(404,'Topilmadi')
    kind,target,action=match[1],unquote(match[2]),match[3];allowed(role,kind)
    if action:
        if role!='support' or kind!='support':raise engine.BookingError(403,'Administratorga yo‘naltirish support roli uchun')
        if action=='escalation-operators' and handler.command=='GET':
            query(handler,());con.execute('BEGIN')
            item=source(con,kind,target);state=assignment(con,kind,target,current)
            if not can_escalate(con,actor,role,kind,item,state):raise engine.BookingError(409,'Murojaatni hozir yo‘naltirib bo‘lmaydi')
            rows=con.execute("SELECT p.username,p.role FROM admin_permissions p JOIN admins a ON a.username=p.username WHERE p.enabled=1 AND p.role='administrator' ORDER BY p.username").fetchall()
            result={'items':[dict(r) for r in rows]}
            audit_view(con,actor,'work-escalation-operators-view',{'kind':kind,'target':target},current)
            con.commit();handler.reply(200,result);return True
        if action=='escalate' and handler.command=='POST':
            if urlparse(handler.path).query:raise ValueError('Unexpected escalation query')
            result=write(con,actor,role,kind,target,handler.body(),current,escalate=True)
            con.commit();handler.reply(200,result);return True
        raise engine.BookingError(405,'Amal ruxsat etilmagan')
    if handler.command=='GET':
        params=query(handler,('before',));con.execute('BEGIN')
        result=view(con,kind,target,current,params.get('before'))
        result['canEscalate']=can_escalate(con,actor,role,kind,result['source'],result['assignment'])
        audit_view(con,actor,'work-history-view',{'kind':kind,'target':target,'before':int(params['before']) if params.get('before') else None},current)
        con.commit();handler.reply(200,result);return True
    if handler.command=='POST':
        if urlparse(handler.path).query:raise ValueError('Unexpected assignment query')
        result=write(con,actor,role,kind,target,handler.body(),current);con.commit();handler.reply(200,result);return True
    raise engine.BookingError(405,'Amal ruxsat etilmagan')
