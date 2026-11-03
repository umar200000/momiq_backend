from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import copy
import hashlib
import json
import secrets
import sqlite3
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request,urlopen

import server
import work_queue
import test_support_tickets as fixtures


class WorkQueueTests(unittest.TestCase):
    save=fixtures.SupportTests.save
    review=fixtures.SupportTests.review
    stop_http=fixtures.SupportTests.stop_http
    req=fixtures.SupportTests.req
    quote=fixtures.SupportTests.quote
    book=fixtures.SupportTests.book
    data=fixtures.SupportTests.data

    def setUp(self):
        fixtures.SupportTests.setUp(self)
        self.operators={}
        with server.db() as con:
            for actor,role in (('manager','administrator'),('helper-one','support'),('helper-two','support'),('moderator','moderation'),('cashier','finance')):
                token=secrets.token_hex(32);self.operators[actor]=token
                con.execute("INSERT INTO admins VALUES(?,'TEST salt','disabled')",(actor,))
                con.execute('INSERT INTO admin_permissions VALUES(?,?,1)',(actor,role))
                con.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),actor,'admin',time.time()+3600))

    def call(self,actor,path,body=None,status=200):
        request=Request(self.base+'/api/admin/'+path,data=json.dumps(body).encode() if body is not None else None,
                        headers={'Cookie':'momiq_admin='+self.operators[actor],'Content-Type':'application/json'})
        try:response=urlopen(request)
        except HTTPError as error:response=error
        with response:
            if status is not None:self.assertEqual(response.status,status)
            payload=json.load(response)
            return payload if status is not None else (response.status,payload)

    def ticket(self):return self.req('/api/support','POST',self.data())['ticket']

    def assignment(self,**changes):
        return {'revision':0,'sourceRevision':1,'assignee':'helper-one','dueAt':None,'reason':'TEST assignment reason','requestId':secrets.token_hex(16),**changes}

    def test_private_queue_reads_commit_audit_before_reply_and_rollback_on_failure(self):
        ticket=self.ticket();target='work-queue/support/'+ticket['id']
        self.call('manager',target,self.assignment())
        cases=[('work-queue?kind=support&filter=mine','work-queue-view',{'kind':'support','filter':'mine','after':None}),
               (target+'?before=999','work-history-view',{'kind':'support','target':ticket['id'],'before':999}),
               ('work-queue/operators?kind=support','work-operators-view',{'kind':'support'})]
        original=work_queue.audit_view
        for route,action,metadata in cases:
            replies=[]
            def reply(status,payload):
                with server.db() as other:
                    event=other.execute('SELECT actor,target FROM audit WHERE action=? ORDER BY id DESC LIMIT 1',(action,)).fetchone()
                    self.assertEqual(event['actor'],'manager');self.assertEqual(json.loads(event['target']),metadata)
                    self.assertNotIn('TEST',event['target'])
                replies.append((status,payload))
            handler=SimpleNamespace(path='/api/admin/'+route,command='GET',operator_role='administrator',reply=reply)
            with server.db() as con:work_queue.route(handler,con,'manager',handler.path.split('?')[0])
            self.assertEqual(replies[0][0],200)
            with server.db() as con:count=con.execute('SELECT count(*) FROM audit').fetchone()[0]
            replies.clear()
            def fail(*args):
                original(*args)
                raise RuntimeError('TEST audit failure')
            with patch.object(work_queue,'audit_view',side_effect=fail),self.assertRaises(RuntimeError):
                with server.db() as con:work_queue.route(handler,con,'manager',handler.path.split('?')[0])
            self.assertEqual(replies,[])
            with server.db() as con:
                self.assertEqual(con.execute('SELECT count(*) FROM audit').fetchone()[0],count)
                self.assertEqual(con.execute('SELECT count(*) FROM work_assignment_events').fetchone()[0],1)
                self.assertEqual(con.execute('SELECT status,revision FROM support_tickets WHERE id=?',(ticket['id'],)).fetchone()[:],('open',1))

    def test_invalid_or_forbidden_queue_reads_do_not_audit_or_disclose(self):
        ticket=self.ticket()
        with server.db() as con:count=con.execute('SELECT count(*) FROM audit').fetchone()[0]
        for actor,path,status in [('cashier','work-queue?kind=support',403),
                                  ('helper-one','work-queue/operators?kind=support',403),
                                  ('manager','work-queue?kind=support&filter=unknown',400),
                                  ('manager','work-queue/support/'+ticket['id']+'?before=0',400),
                                  ('manager','work-queue/support/'+'f'*32,404)]:
            self.call(actor,path,status=status)
        with server.db() as con:self.assertEqual(con.execute('SELECT count(*) FROM audit').fetchone()[0],count)

    def test_claim_reassign_retry_closed_history_and_client_privacy(self):
        ticket=self.ticket();target='work-queue/support/'+ticket['id']
        self.req('/api/admin/'+target,status=401)
        self.call('cashier',target,status=403);self.call('moderator','work-queue?kind=support',status=403)
        page=self.call('helper-one','work-queue?kind=support&filter=unassigned')
        self.assertEqual(page['items'][0]['source']['target'],ticket['id'])
        first=self.assignment();saved=self.call('helper-one',target,first)
        self.assertEqual(saved['assignment']['assignee'],'helper-one')
        self.assertEqual(self.call('helper-one','work-queue?kind=support&filter=mine')['items'][0]['assignment']['revision'],1)
        self.assertEqual(self.call('helper-one','work-queue?kind=support&filter=unassigned')['items'],[])
        self.call('helper-two',target,self.assignment(revision=1,assignee='helper-two'),status=403)
        due=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
        self.call('helper-one',target,self.assignment(revision=1,dueAt=due),status=403)
        second=self.assignment(revision=1,assignee='helper-two',dueAt=due)
        self.call('manager',target,second)
        self.assertEqual(self.call('manager','work-queue?kind=support&filter=overdue')['items'][0]['source']['target'],ticket['id'])
        replay=self.call('helper-one',target,first)
        self.assertEqual(replay['event']['id'],saved['event']['id']);self.assertEqual(replay['assignment']['assignee'],'helper-two')
        self.call('helper-one',target,{**first,'reason':'Changed TEST reason'},status=409)
        owner=self.req('/api/support/'+ticket['id'])
        self.assertNotIn('assignment',owner);self.assertNotIn('helper-one',json.dumps(owner));self.assertEqual(owner['ticket']['revision'],1)
        self.call('manager','support/'+ticket['id'],{'text':'TEST complete','image':None,'action':'resolve','revision':1,'requestId':secrets.token_hex(16)})
        self.assertEqual(self.call('manager','work-queue?kind=support')['items'],[])
        history=self.call('manager',target)
        self.assertEqual(len(history['items']),2);self.assertFalse(history['source']['active']);self.assertFalse(history['assignment']['overdue'])
        self.call('manager',target,self.assignment(revision=2,sourceRevision=2),status=409)
        self.assertEqual(self.call('helper-one',target,first)['event']['id'],saved['event']['id'])

    def test_two_operators_cannot_claim_one_revision_and_rollback_all_effects(self):
        ticket=self.ticket();target='work-queue/support/'+ticket['id'];barrier=threading.Barrier(2)
        def claim(actor):
            barrier.wait();return self.call(actor,target,self.assignment(assignee=actor),status=None)[0]
        with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(claim,('helper-one','helper-two')))
        self.assertEqual(sorted(statuses),[200,409])
        with server.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM work_assignment_events').fetchone()[0],1)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM wallet_entries').fetchone()[0],0)
        other=self.ticket();path='work-queue/support/'+other['id'];payload=self.assignment()
        with server.db() as con:con.execute("CREATE TRIGGER test_reject_work_audit BEFORE INSERT ON audit WHEN NEW.action='work-assignment' BEGIN SELECT RAISE(ABORT,'TEST audit failed'); END")
        self.call('manager',path,payload,status=500)
        with server.db() as con:
            self.assertFalse(con.execute('SELECT 1 FROM work_assignments WHERE target=?',(other['id'],)).fetchone())
            self.assertFalse(con.execute('SELECT 1 FROM work_assignment_events WHERE target=?',(other['id'],)).fetchone())
            con.execute('DROP TRIGGER test_reject_work_audit')
        self.call('manager',path,payload)

    def test_listing_work_uses_current_moderation_and_operator_role(self):
        changed=copy.deepcopy(self.listing);changed['listings'][0]['price']=600000
        self.save(changed,revision=2)
        target='work-queue/listing/abc%3Aboarding'
        row=self.call('moderator',target);self.assertTrue(row['source']['active'])
        payload=self.assignment(sourceRevision=row['source']['revision'],assignee='cashier')
        self.call('manager',target,payload,status=409)
        payload=self.assignment(sourceRevision=row['source']['revision'],assignee='moderator')
        self.call('moderator',target,payload)
        self.call('helper-one',target,status=403)
        self.call('moderator','listings/abc/boarding/review',{'decision':'reject','reason':'TEST needs revision','testOnly':True,'_revision':row['source']['revision']})
        self.assertEqual(self.call('moderator','work-queue?kind=listing')['items'],[])
        self.assertEqual(self.call('moderator',target)['assignment']['assignee'],'moderator')

    def test_report_decision_closes_work_without_deleting_assignment_history(self):
        chat=self.req('/api/conversations','POST',{'listingId':'abc:boarding'})
        message=self.req('/api/conversations/'+chat['id']+'/messages','POST',{'text':'TEST reported text','requestId':secrets.token_hex(16)},user='abc')
        report=self.req('/api/conversations/'+chat['id']+'/reports','POST',{'messageId':message['id'],'reason':'TEST report','requestId':secrets.token_hex(16)})
        target='work-queue/chat_report/'+str(report['id'])
        self.call('moderator',target,self.assignment(sourceRevision=0,assignee='moderator'))
        self.call('moderator','chat-reports/'+str(report['id'])+'/review',{'revision':0,'decision':'dismiss','reason':'TEST reviewed'})
        self.assertEqual(self.call('moderator','work-queue?kind=chat_report')['items'],[])
        self.assertEqual(len(self.call('moderator',target)['items']),1)

    def test_history_pages_immutability_and_disabled_operator_are_explicit(self):
        ticket=self.ticket();target='work-queue/support/'+ticket['id']
        for revision in range(22):self.call('manager',target,self.assignment(revision=revision,assignee='helper-one' if revision%2==0 else 'helper-two'))
        first=self.call('manager',target);second=self.call('manager',target+'?before='+first['nextCursor'])
        self.assertEqual(len(first['items']),20);self.assertEqual(len(second['items']),2)
        self.assertFalse({r['id'] for r in first['items']} & {r['id'] for r in second['items']})
        for sql in ("UPDATE work_assignment_events SET reason='forged'",'DELETE FROM work_assignment_events', 'INSERT OR REPLACE INTO work_assignment_events SELECT * FROM work_assignment_events WHERE id=1', "INSERT OR REPLACE INTO work_assignment_events SELECT 999,kind,target,revision,actor,reason,before_state,after_state,created,request_id,fingerprint FROM work_assignment_events WHERE id=1"):
            with self.assertRaises(sqlite3.IntegrityError):
                with server.db() as con:con.execute(sql)
        with server.db() as con:con.execute("UPDATE admin_permissions SET enabled=0 WHERE username='helper-two'")
        self.assertFalse(self.call('manager',target)['assignment']['assigneeActive'])
        available=self.call('manager','work-queue/operators?kind=support')['items']
        self.assertNotIn('helper-two',[x['username'] for x in available]);self.assertNotIn('cashier',[x['username'] for x in available])
        self.call('helper-one','work-queue/operators?kind=support',status=403)
        self.call('manager',target,self.assignment(revision=22,assignee='helper-two',dueAt=datetime.now(timezone.utc).isoformat()),status=409)
        self.call('manager',target,self.assignment(revision=21),status=409)
        self.call('manager',target,{**self.assignment(revision=22),'administrator':True},status=400)

    def test_active_queue_pages_filters_and_query_validation(self):
        ticket=self.ticket()
        with server.db() as con:
            columns=[r[1] for r in con.execute('PRAGMA table_info(support_tickets)') if r[1]!='seq']
            original=dict(con.execute('SELECT * FROM support_tickets WHERE id=?',(ticket['id'],)).fetchone())
            for n in range(22):
                row={**original,'id':format(n+1,'032x')}
                con.execute('INSERT INTO support_tickets('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',[row[c] for c in columns])
        first=self.call('helper-one','work-queue?kind=support&filter=all')
        second=self.call('helper-one','work-queue?kind=support&filter=all&after='+first['nextCursor'])
        identities=[r['source']['target'] for r in first['items']+second['items']]
        self.assertEqual(len(identities),23);self.assertEqual(len(set(identities)),23);self.assertIsNone(second['nextCursor'])
        for suffix in ('&filter=unknown','&kind=listing','&after=bad','&owner=other'):
            self.call('helper-one','work-queue?kind=support'+suffix,status=400)
        for due in ('2026-10-29T10:00:00','invalid'):
            self.call('manager','work-queue/support/'+ticket['id'],self.assignment(dueAt=due),status=400)


if __name__=='__main__':unittest.main()
