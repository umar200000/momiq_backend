import json
import secrets
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import server
import catalog
import work_queue
import test_work_queue as fixtures

class WorkEscalationTests(unittest.TestCase):
    setUp=fixtures.WorkQueueTests.setUp
    save=fixtures.WorkQueueTests.save
    review=fixtures.WorkQueueTests.review
    stop_http=fixtures.WorkQueueTests.stop_http
    req=fixtures.WorkQueueTests.req
    quote=fixtures.WorkQueueTests.quote
    book=fixtures.WorkQueueTests.book
    data=fixtures.WorkQueueTests.data
    call=fixtures.WorkQueueTests.call
    assignment=fixtures.WorkQueueTests.assignment

    def ticket(self,content=True):
        return self.req('/api/support','POST',self.data(**({'target':{'kind':'listing','id':'abc:boarding'}} if content else {})))['ticket']

    def snapshot(self,excluded=()):
        with server.db() as con:
            names=[r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'") if r[0] not in excluded]
            return {n:[tuple(r) for r in con.execute('SELECT * FROM "'+n+'" ORDER BY rowid')] for n in names}

    def test_escalation_assigns_administrator_with_immutable_history_without_source_or_money_changes(self):
        ticket=self.ticket();path='work-queue/support/'+ticket['id']
        self.assertTrue(self.call('helper-one',path)['canEscalate'])
        operators=self.call('helper-one',path+'/escalation-operators')['items']
        self.assertIn('manager',[o['username'] for o in operators]);self.assertTrue(all(o['role']=='administrator' for o in operators))
        data=self.assignment(assignee='manager');before=self.snapshot(('audit','attempts','work_assignments','work_assignment_events'))
        saved=self.call('helper-one',path+'/escalate',data)
        self.assertEqual(saved['assignment']['assignee'],'manager');self.assertTrue(saved['event']['after']['escalated'])
        self.assertEqual(self.snapshot(('audit','attempts','work_assignments','work_assignment_events')),before)
        self.assertFalse(self.call('helper-one',path)['canEscalate'])
        self.assertEqual(self.call('manager','work-queue?kind=support&filter=mine')['items'][0]['source']['target'],ticket['id'])
        self.assertEqual(self.call('helper-one',path+'/escalate',data)['event']['id'],saved['event']['id'])
        self.call('helper-one',path,data,status=409)
        owner=self.req('/api/support/'+ticket['id'])
        self.assertNotIn('manager',json.dumps(owner));self.assertNotIn('assignment',owner)
        with server.db() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM work_assignment_events').fetchone()[0],1)
            event=con.execute("SELECT actor,target FROM audit WHERE action='work-escalation'").fetchone()
            self.assertEqual(event['actor'],'helper-one');self.assertEqual(json.loads(event['target'])['after']['assignee'],'manager')
        self.call('manager','support/'+ticket['id'],{'text':'TEST resolved','image':None,'action':'resolve','revision':1,'requestId':secrets.token_hex(16)})
        self.assertEqual(self.call('helper-one',path+'/escalate',data)['event']['id'],saved['event']['id'])
        self.call('helper-one',path+'/escalate',self.assignment(assignee='manager',revision=1,sourceRevision=2),status=409)

    def test_scoped_escalation_rejects_role_target_deadline_revision_and_extra_fields_without_writes(self):
        ticket=self.ticket();path='work-queue/support/'+ticket['id'];data=self.assignment(assignee='manager')
        for actor,body,status in [('cashier',data,403),('moderator',data,403),('manager',data,403),
                                 ('helper-one',{**data,'assignee':'helper-two'},409),('helper-one',{**data,'dueAt':'2026-11-01T00:00:00Z'},409),
                                 ('helper-one',{**data,'sourceRevision':999},409),('helper-one',{**data,'revision':2},409),
                                 ('helper-one',{**data,'reason':''},400),('helper-one',{**data,'actor':'manager'},400)]:
            before=self.snapshot();self.call(actor,path+'/escalate',body,status=status);self.assertEqual(self.snapshot(),before)
        before=self.snapshot();self.req('/api/admin/'+path+'/escalate','POST',data,status=401);self.assertEqual(self.snapshot(),before)
        self.call('helper-one',path+'/escalate?admin=1',data,status=400)
        self.call('helper-one','work-queue/operators?kind=support',status=403)
        ordinary=self.ticket(False);ordinary_path='work-queue/support/'+ordinary['id']
        self.assertFalse(self.call('helper-one',ordinary_path)['canEscalate'])
        self.call('helper-one',ordinary_path+'/escalation-operators',status=409)
        self.call('helper-one',ordinary_path+'/escalate',data,status=409)

    def test_appeal_handoff_keeps_support_unable_to_decide_or_restore_listing(self):
        with server.db() as con:
            rejected=catalog.review(con,'abc','boarding',{'decision':'reject','reason':'TEST rejected',
                '_revision':catalog.revision(con,'abc'),'testOnly':True},'manager','test')
        target=rejected['moderation']['boarding']['appealTarget']
        ticket=self.req('/api/support','POST',self.data(target=target),user='abc')['ticket']
        path='work-queue/support/'+ticket['id']
        self.call('helper-one',path+'/escalate',self.assignment(assignee='manager'))
        answer={'text':'TEST support cannot decide','image':None,'action':'resolve','revision':1,'requestId':secrets.token_hex(16)}
        self.call('helper-one','support/'+ticket['id'],answer,status=403)
        administrator=self.call('manager','support/'+ticket['id']);self.assertTrue(administrator['canResolve'])
        with server.db() as con:self.assertEqual(catalog.document(con,'abc')['moderation']['boarding']['status'],'rejected')
        self.assertEqual(administrator['ticket']['revision'],1)

    def test_claimed_work_cannot_be_stolen_and_disabled_administrator_cannot_receive(self):
        ticket=self.ticket();path='work-queue/support/'+ticket['id']
        self.call('helper-one',path,self.assignment())
        self.call('helper-two',path+'/escalate',self.assignment(revision=1,assignee='manager'),status=409)
        self.call('helper-two',path+'/escalation-operators',status=409)
        with server.db() as con:con.execute("UPDATE admin_permissions SET enabled=0 WHERE username='manager'")
        self.call('helper-one',path+'/escalate',self.assignment(revision=1,assignee='manager'),status=409)
        operators=self.call('helper-one',path+'/escalation-operators')['items'];self.assertNotIn('manager',[o['username'] for o in operators])
        with server.db() as con:con.execute("UPDATE admin_permissions SET enabled=1 WHERE username='manager'")
        result=self.call('helper-one',path+'/escalate',self.assignment(revision=1,assignee='manager'))
        self.assertEqual(result['assignment']['revision'],2)

    def test_parallel_escalations_make_one_assignment_and_audit_failure_rolls_back(self):
        ticket=self.ticket();path='work-queue/support/'+ticket['id'];barrier=threading.Barrier(2)
        def send(actor):
            barrier.wait();return self.call(actor,path+'/escalate',self.assignment(assignee='manager'),status=None)[0]
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(send,['helper-one','helper-two']))
        self.assertEqual(sorted(results),[200,409])
        other=self.ticket();other_path='work-queue/support/'+other['id']
        with server.db() as con:con.execute("CREATE TRIGGER fail_test_escalation BEFORE INSERT ON audit WHEN NEW.action='work-escalation' BEGIN SELECT RAISE(ABORT,'TEST audit failure'); END")
        before=self.snapshot();self.call('helper-one',other_path+'/escalate',self.assignment(assignee='manager'),status=500)
        self.assertEqual(self.snapshot(),before)

    def test_administrator_discovery_audits_before_disclosure_and_failure_returns_no_data(self):
        ticket=self.ticket();path='/api/admin/work-queue/support/'+ticket['id']+'/escalation-operators';replies=[]
        def reply(status,payload):
            with server.db() as con:
                event=con.execute("SELECT actor,target FROM audit WHERE action='work-escalation-operators-view' ORDER BY id DESC LIMIT 1").fetchone()
                self.assertEqual(event['actor'],'helper-one');self.assertEqual(json.loads(event['target']),{'kind':'support','target':ticket['id']})
            replies.append(payload)
        handler=SimpleNamespace(path=path,command='GET',operator_role='support',reply=reply)
        with server.db() as con:work_queue.route(handler,con,'helper-one',path)
        self.assertEqual(len(replies),1);replies.clear();before=self.snapshot();original=work_queue.audit_view
        def failed(*args):original(*args);raise RuntimeError('TEST unavailable audit')
        with patch.object(work_queue,'audit_view',side_effect=failed),self.assertRaises(RuntimeError):
            with server.db() as con:work_queue.route(handler,con,'helper-one',path)
        self.assertEqual(replies,[]);self.assertEqual(self.snapshot(),before)

if __name__=='__main__':unittest.main()
