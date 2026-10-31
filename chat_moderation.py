"""Participant blocking and message reports; moderator evidence access is audited."""
import re
import json
from urllib.parse import parse_qs, urlparse

from conversations import ChatError, number, participant, quota, summary, timestamp


def text(value, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('Reason required')
    return value.strip()


def revision(value):
    if type(value) is not int or value < 0:
        raise ChatError(428, 'Avval joriy holatni yuklang')
    return value


def report_json(row):
    return {'id': str(row['id']), 'messageId': str(row['message_id']),
            'reason': row['reason'], 'status': row['status'], 'revision': row['revision'],
            'created': row['created'], 'reviewedAt': row['reviewed_at'], 'reviewReason': row['review_reason']}


def audit(con, actor, action, target):
    con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)', (actor, action, target, timestamp()))


def route(handler, con, user, path):
    match = re.fullmatch(r'/api/conversations/([a-f0-9]{32})/(block|reports)', path)
    if match:
        identity, action = match.groups()
        query=parse_qs(urlparse(handler.path).query,keep_blank_values=True)
        if any(len(values)!=1 for values in query.values()) or set(query)-({'before'} if action=='reports' and handler.command=='GET' else set()):
            raise ValueError('Unexpected moderation query')
        if handler.command=='POST' and urlparse(handler.path).query:raise ValueError('Unexpected mutation query')
        if action == 'reports' and handler.command == 'GET':
            con.execute('BEGIN')
            participant(con, identity, user)
            before = query.get('before', [None])[0]
            args = [identity, user]; clause = ''
            if before is not None: clause = ' AND r.id<?'; args.append(number(before))
            rows = con.execute('SELECT r.* FROM chat_reports r JOIN conversation_messages m ON m.id=r.message_id WHERE m.conversation_id=? AND r.reporter_id=?'+clause+' ORDER BY r.id DESC LIMIT 21', args).fetchall()
            handler.reply(200, {'items': [report_json(r) for r in rows[:20]], 'nextCursor':str(rows[19]['id']) if len(rows)>20 else None})
            return True
        if handler.command != 'POST': raise ChatError(404, 'Topilmadi')
        data = handler.body()
        allowed={'blocked','revision'} if action=='block' else {'messageId','reason','requestId'}
        if set(data)-allowed:raise ValueError('Unexpected moderation fields')
        con.execute('BEGIN IMMEDIATE')
        row = participant(con, identity, user)
        peer = row['sitter_id'] if row['customer_id'] == user else row['customer_id']
        if action == 'block':
            wanted = data.get('blocked')
            if type(wanted) is not bool: raise ValueError('Boolean required')
            expected = revision(data.get('revision'))
            current = con.execute('SELECT * FROM chat_blocks WHERE blocker_id=? AND blocked_id=?', (user, peer)).fetchone()
            actual = current['revision'] if current else 0
            if expected != actual:
                if not (current and actual == expected+1 and bool(current['active']) == wanted):
                    raise ChatError(409, 'Blok holati o‘zgargan. Yangilang.')
            else:
                con.execute('INSERT INTO chat_blocks VALUES(?,?,?,?,?) ON CONFLICT(blocker_id,blocked_id) DO UPDATE SET active=excluded.active,revision=excluded.revision,updated=excluded.updated',
                            (user, peer, int(wanted), actual+1, timestamp()))
            result = summary(con, row, user)
        else:
            message_id = number(data.get('messageId'))
            reason = text(data.get('reason'), 1000)
            request = data.get('requestId')
            if not isinstance(request, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,100}', request):
                raise ValueError('Stable requestId required')
            message = con.execute('SELECT * FROM conversation_messages WHERE conversation_id=? AND id=?', (identity, message_id)).fetchone()
            if not message or message['sender_id'] == user: raise ChatError(404, 'Xabar topilmadi')
            existing = con.execute('SELECT * FROM chat_reports WHERE reporter_id=? AND (request_id=? OR message_id=?)', (user, request, message_id)).fetchall()
            if existing:
                if len(existing) != 1 or existing[0]['message_id'] != message_id or existing[0]['reason'] != reason:
                    raise ChatError(409, 'Bu xabar uchun murojaat mavjud yoki so‘rov identifikatori takrorlangan')
                result = report_json(existing[0])
            else:
                quota(con, user, 'report', 10)
                created = timestamp()
                cursor = con.execute("INSERT INTO chat_reports(reporter_id,message_id,request_id,reason,status,created) VALUES(?,?,?,?,'open',?)", (user, message_id, request, reason, created))
                con.execute("INSERT INTO chat_report_history VALUES(?,0,'open',?,?,?)", (cursor.lastrowid, user, reason, created))
                result = report_json(con.execute('SELECT * FROM chat_reports WHERE id=?', (cursor.lastrowid,)).fetchone())
        con.commit()
        handler.reply(200, result)
        return True
    if path == '/api/admin/chat-reports' and handler.command == 'GET':
        query = parse_qs(urlparse(handler.path).query,keep_blank_values=True)
        if set(query)-{'status','before'} or any(len(v)!=1 for v in query.values()):raise ValueError('Invalid report query')
        status = query.get('status', ['open'])[0]
        if status not in ('open','dismissed','removed','all'): raise ValueError('Invalid status')
        args = []; clauses = []
        if status != 'all': clauses.append('status=?'); args.append(status)
        before = query.get('before', [None])[0]
        if before is not None: clauses.append('id<?'); args.append(number(before))
        where = ' WHERE '+' AND '.join(clauses) if clauses else ''
        con.execute('BEGIN')
        rows = con.execute('SELECT * FROM chat_reports'+where+' ORDER BY id DESC LIMIT 21', args).fetchall()
        result={'items':[report_json(r) for r in rows[:20]], 'nextCursor':str(rows[19]['id']) if len(rows)>20 else None}
        audit(con,user,'chat-report-list',json.dumps({'status':status,'before':int(before) if before is not None else None}))
        con.commit();handler.reply(200,result)
        return True
    match = re.fullmatch(r'/api/admin/chat-reports/([1-9][0-9]{0,17})/(evidence|image|review)', path)
    if not match: return False
    identity, action = int(match[1]), match[2]
    data = handler.body() if handler.command == 'POST' else None
    if handler.command=='POST' and (set(data)-{'revision','reason','decision'} or urlparse(handler.path).query):
        raise ValueError('Unexpected moderation fields')
    con.execute('BEGIN IMMEDIATE')
    report = con.execute('SELECT * FROM chat_reports WHERE id=?', (identity,)).fetchone()
    if not report: raise ChatError(404, 'Murojaat topilmadi')
    message = con.execute('SELECT * FROM conversation_messages WHERE id=?', (report['message_id'],)).fetchone()
    if handler.command == 'GET' and action in ('evidence','image'):
        audit(con, user, 'chat-report-'+action, str(identity))
        if action == 'image':
            if not message['image']: raise ChatError(404, 'Rasm yo‘q')
            result = {'image': message['image']}
        else:
            history = [dict(r) for r in con.execute('SELECT revision,status,actor,reason,created FROM chat_report_history WHERE report_id=? ORDER BY revision', (identity,))]
            result = {'report': report_json(report), 'message': {'text':message['text'], 'hasImage':bool(message['image']), 'created':message['created'], 'senderRole':message['sender_role'], 'hidden':bool(message['hidden'])}, 'history':history}
    elif handler.command == 'POST' and action == 'review':
        expected = revision(data.get('revision')); reason = text(data.get('reason'), 1000)
        decision = data.get('decision')
        if decision not in ('dismiss','remove'): raise ValueError('Invalid decision')
        status = 'dismissed' if decision == 'dismiss' else 'removed'
        if report['status'] != 'open' or expected != report['revision']:
            if not (report['revision'] == expected+1 and report['status'] == status and report['review_reason'] == reason and report['reviewed_by'] == user):
                raise ChatError(409, 'Murojaat boshqa qaror bilan o‘zgargan. Yangilang.')
        else:
            reviewed = timestamp()
            if decision == 'remove':
                con.execute('UPDATE conversation_messages SET hidden=1 WHERE id=?', (message['id'],))
                con.execute('INSERT OR IGNORE INTO chat_changes(conversation_id,message_id,created) VALUES(?,?,?)', (message['conversation_id'],message['id'],reviewed))
            con.execute('UPDATE chat_reports SET status=?,revision=revision+1,reviewed_at=?,reviewed_by=?,review_reason=? WHERE id=?', (status,reviewed,user,reason,identity))
            con.execute('INSERT INTO chat_report_history VALUES(?,?,?,?,?,?)', (identity,expected+1,status,user,reason,reviewed))
            audit(con, user, 'chat-report-'+decision, str(identity))
        result = report_json(con.execute('SELECT * FROM chat_reports WHERE id=?', (identity,)).fetchone())
    else: raise ChatError(404, 'Topilmadi')
    con.commit()
    handler.reply(200, result)
    return True
