import json
import secrets
import sqlite3
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import booking_reviews
import catalog
import server
import support_resolutions
import support_tickets
import test_support_targets


class AppealResolutionTests(unittest.TestCase):
    setUp=test_support_targets.SupportTargetTests.setUp
    save=test_support_targets.SupportTargetTests.save
    review=test_support_targets.SupportTargetTests.review
    stop_http=test_support_targets.SupportTargetTests.stop_http
    req=test_support_targets.SupportTargetTests.req
    admin=test_support_targets.SupportTargetTests.admin
    data=test_support_targets.SupportTargetTests.data
    reply=test_support_targets.SupportTargetTests.reply
    reject_listing=test_support_targets.SupportTargetTests.reject_listing

    def prepare(self):
        created=self.req('/api/support','POST',self.data(target=self.reject_listing()),user='abc')
        identity=created['ticket']['id'];path='/api/admin/support/'+identity
        page=self.admin(path)
        body=self.reply(action='resolve',decisionVersion=page['decisionContext']['version'])
        return identity,path,page,body

    def snapshot(self):
        with server.db() as con:
            names=[r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            return {name:sorted([tuple(r) for r in con.execute('SELECT * FROM "'+name.replace('"','""')+'"')],key=repr) for name in names}

    def test_closure_requires_reviewed_context_and_preserves_private_immutable_decision(self):
        identity,path,page,body=self.prepare();before=self.snapshot()
        self.admin(path,{k:v for k,v in body.items() if k!='decisionVersion'},status=428)
        self.admin(path,{**body,'decisionVersion':'invalid'},status=400)
        self.admin(path,{**body,'snapshot':{'status':'approved'}},status=400)
        self.assertEqual(self.snapshot(),before)
        closed=self.admin(path,body);resolution=closed['items'][-1]['resolution']
        self.assertEqual(resolution['snapshot'],page['decisionContext']['snapshot'])
        self.assertEqual(resolution['sourceEvent'],page['decisionContext']['sourceEvent'])
        self.assertEqual(resolution['snapshot']['status'],'rejected')
        owner=self.req('/api/support/'+identity,user='abc')
        self.assertNotIn('decisionContext',owner)
        self.assertNotIn('sourceEvent',owner['items'][-1]['resolution'])
        self.assertNotIn('test-admin',json.dumps(owner))
        self.req('/api/support/'+identity,user='customer',status=404)
        with server.db() as con:
            row=tuple(con.execute('SELECT * FROM support_resolutions').fetchone())
            for sql,args in [('UPDATE support_resolutions SET snapshot=?',('{}',)),
                             ('DELETE FROM support_resolutions',()),
                             ('INSERT OR REPLACE INTO support_resolutions VALUES(?,?,?,?,?,?)',row)]:
                with self.assertRaises(sqlite3.IntegrityError):con.execute(sql,args)
            self.assertEqual(tuple(con.execute('SELECT * FROM support_resolutions').fetchone()),row)
            self.assertEqual(catalog.document(con,'abc')['moderation']['boarding']['status'],'rejected')
            audit=json.loads(con.execute("SELECT target FROM audit WHERE action='support-resolve' ORDER BY id DESC LIMIT 1").fetchone()[0])
            self.assertEqual(audit['resolutionMessageId'],row[0])
            self.assertEqual(audit['sourceEvent'],resolution['sourceEvent'])

    def test_stale_decision_fails_atomically_and_retry_retains_recorded_source(self):
        identity,path,page,body=self.prepare()
        self.reject_listing('TEST changed before closure');before=self.snapshot()
        self.admin(path,body,status=409)
        self.assertEqual(self.snapshot(),before)
        body['decisionVersion']=self.admin(path)['decisionContext']['version']
        closed=self.admin(path,body)
        self.assertEqual(closed['items'][-1]['resolution']['snapshot']['decision']['reason'],'TEST changed before closure')
        self.reject_listing('TEST changed after closure')
        before=self.snapshot();retry=self.admin(path,body)
        self.assertEqual(retry['items'],closed['items'])
        self.assertEqual(self.snapshot(),before)
        self.admin(path,{**body,'decisionVersion':retry['decisionContext']['version']},status=409)
        self.assertEqual(self.snapshot(),before)

    def test_parallel_closure_retries_write_one_resolution_and_one_notice(self):
        identity,path,page,body=self.prepare();gate=threading.Barrier(2)
        def close(_):
            gate.wait()
            with server.db() as con:return support_tickets.write(con,'test-admin',identity,body,server.photo,True,'test')
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(close,range(2)))
        self.assertEqual(results[0],results[1])
        with server.db() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM support_resolutions').fetchone()[0],1)
            self.assertEqual(con.execute("SELECT count(*) FROM notifications WHERE source_key=?",('support:'+identity+':2',)).fetchone()[0],1)
            # A normal reply cannot acquire a forged resolution by SQL linkage.
            first=con.execute('SELECT id FROM support_messages WHERE revision=1 AND ticket_id=?',(identity,)).fetchone()[0]
            row=list(con.execute('SELECT * FROM support_resolutions').fetchone());row[0]=first
            with self.assertRaises(sqlite3.IntegrityError):con.execute('INSERT INTO support_resolutions VALUES(?,?,?,?,?,?)',row)

    def test_failed_resolution_write_rolls_back_message_quota_notice_and_audit(self):
        identity,path,page,body=self.prepare();before=self.snapshot();original=support_resolutions.attach
        def fail(*args):
            original(*args)
            raise RuntimeError('TEST resolution failure')
        with patch.object(support_resolutions,'attach',side_effect=fail):self.admin(path,body,status=500)
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.admin(path,body)['ticket']['status'],'resolved')


class ReviewResolutionTests(unittest.TestCase):
    setUp=test_support_targets.ReviewTargetTests.setUp
    save=test_support_targets.ReviewTargetTests.save
    review=test_support_targets.ReviewTargetTests.review
    quote=test_support_targets.ReviewTargetTests.quote
    request=test_support_targets.ReviewTargetTests.request
    act=test_support_targets.ReviewTargetTests.act
    accepted=test_support_targets.ReviewTargetTests.accepted
    active=test_support_targets.ReviewTargetTests.active
    complete=test_support_targets.ReviewTargetTests.complete
    write=test_support_targets.ReviewTargetTests.write
    data=test_support_targets.ReviewTargetTests.data

    def test_review_resolution_records_actual_moderation_history_not_owner_visibility(self):
        booking=self.complete();review=self.write(booking,self.data())['review'];identity=int(review['id'])
        with server.db() as con:
            con.execute("INSERT INTO admins VALUES('test-admin','TEST','disabled')")
            con.execute("INSERT INTO admin_permissions VALUES('test-admin','administrator',1)")
            con.commit()
            booking_reviews.moderate(con,'test-admin',identity,{'hidden':True,'revision':1,'requestId':secrets.token_hex(16),'reason':'TEST hidden'},self.start)
            target=booking_reviews.owner_view(con,booking['id'],'customer',self.start)['appealTarget'];con.commit()
            created=support_tickets.write(con,'customer',None,{'subject':'TEST appeal','topic':'safety','bookingId':None,'text':'TEST reason','image':None,'revision':0,'requestId':secrets.token_hex(16),'action':'reply','target':target},server.photo,environment='test');con.commit()
            ticket=created['ticket']['id']
            first=support_tickets.view(con,ticket,'test-admin',True)['decisionContext'];con.commit()
            booking_reviews.moderate(con,'test-admin',identity,{'hidden':False,'revision':2,'requestId':secrets.token_hex(16),'reason':'TEST restored'},self.start);con.commit()
            current=support_tickets.view(con,ticket,'test-admin',True)['decisionContext']
            self.assertNotEqual(first['version'],current['version']);self.assertFalse(current['snapshot']['hidden'])
            self.assertEqual(current['snapshot']['decisionRevision'],3);self.assertEqual(current['sourceEvent'],'review:'+str(identity)+':3');con.commit()
            closed=support_tickets.write(con,'test-admin',ticket,{'text':'TEST appeal reviewed','image':None,'revision':1,'requestId':secrets.token_hex(16),'action':'resolve','decisionVersion':current['version']},server.photo,True,'test')
            self.assertEqual(closed['items'][-1]['resolution']['snapshot']['decision']['reason'],'TEST restored')
            self.assertFalse(con.execute('SELECT hidden FROM booking_reviews WHERE id=?',(identity,)).fetchone()[0])
