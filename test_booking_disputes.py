from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import secrets
import sqlite3
import threading
import unittest
from unittest.mock import patch

import booking_disputes as disputes
import booking_engine as engine
import migrations
import notifications
import server
import wallet
import test_booking_engine as fixtures
from test_media import fixture_image
import test_booking_http
import test_support_tickets


class DisputeTests(unittest.TestCase):
    def test_decision_appeal_is_owner_scoped_and_does_not_reopen_booking_or_refund_twice(self):
        import support_tickets
        b=self.act(self.request())
        case=self.report(b)
        def write(actor,body,ticket=None,admin=False):
            with server.db() as con:return support_tickets.write(con,actor,ticket,body,server.photo,admin,'local')
        data={'action':'reply','subject':'TEST appeal','topic':'dispute_appeal','bookingId':b['id'],
              'text':'TEST please review','image':None,'revision':0,'requestId':secrets.token_hex(16),'appealRevision':1}
        self.expect_error(404,lambda:write('customer',data))
        closed=self.resolve(b,self.decision(case));rev=closed['case']['revision']
        self.expect_error(409,lambda:write('customer',data))
        data['appealRevision']=rev
        self.expect_error(404,lambda:write('stranger',data))
        opened=write('customer',data);identity=opened['ticket']['id']
        self.assertEqual(write('customer',data)['acknowledgement'],opened['acknowledgement'])
        self.assertEqual(opened['disputeAppeal']['revision'],rev)
        with server.db() as con:
            con.execute("INSERT INTO admins VALUES('test-support','00','00')")
            con.execute("INSERT INTO admin_permissions VALUES('test-support','support',1)")
            limited=support_tickets.view(con,identity,'test-support',True)
            self.assertFalse(limited['canResolve'])
            self.assertEqual(set(limited['disputeAppeal']),{'bookingId','revision','eventId'})
            money=list(con.execute('SELECT * FROM wallet_entries ORDER BY id'))
        import work_queue
        with server.db() as con:
            assigned=work_queue.write(con,'test-support','support','support',identity,
                {'revision':0,'sourceRevision':1,'assignee':'admin','dueAt':None,'reason':'TEST review request',
                 'requestId':secrets.token_hex(16)},self.start,escalate=True)
            self.assertEqual(assigned['assignment']['assignee'],'admin')
        reply={'action':'resolve','text':'TEST administrator response','image':None,'revision':1,'requestId':secrets.token_hex(16)}
        self.expect_error(403,lambda:write('test-support',reply,identity,True))
        self.expect_error(428,lambda:write('admin',reply,identity,True))
        self.expect_error(409,lambda:write('admin',{**reply,'reviewedDisputeEventId':'0'},identity,True))
        reply['reviewedDisputeEventId']=opened['disputeAppeal']['eventId']
        result=write('admin',reply,identity,True)
        self.assertEqual(result['ticket']['status'],'resolved')
        self.assertEqual(write('admin',reply,identity,True)['acknowledgement'],result['acknowledgement'])
        with server.db() as con:
            self.assertEqual(list(con.execute('SELECT * FROM wallet_entries ORDER BY id')),money)
            audit=json.loads(con.execute("SELECT target FROM audit WHERE action='support-resolve'").fetchone()[0])
            self.assertEqual(audit['disputeEventId'],reply['reviewedDisputeEventId'])
        self.assertEqual(self.read(b)['case'],closed['case'])

    setUp=fixtures.BookingEngineTests.setUp
    save=fixtures.BookingEngineTests.save
    review=fixtures.BookingEngineTests.review
    quote=fixtures.BookingEngineTests.quote
    request=fixtures.BookingEngineTests.request
    act=fixtures.BookingEngineTests.act
    expect_error=fixtures.BookingEngineTests.expect_error

    def read(self,b,user='customer',now=None,admin=False):
        with server.db() as con:return disputes.view(con,b['id'],user,now or self.start,admin)

    def payload(self,b,**changes):
        return {'action':'report','kind':'no_show','revision':0,'bookingRevision':b['revision'],
                'text':'TEST private evidence','image':None,'requestId':secrets.token_hex(16),**changes}

    def report(self,b,data=None,user='customer',now=None):
        with server.db() as con:return disputes.write(con,b['id'],user,data or self.payload(b),server.photo,now or self.start+timedelta(minutes=30),'local')

    def decision(self,case,**changes):
        return {'revision':case['case']['revision'],'bookingRevision':case['bookingRevision'],
                'requestId':secrets.token_hex(16),'outcome':'not_started','reason':'TEST verified not started',
                'fault':'sitter','emergency':False,'refundMinor':case['refundableMinor'],**changes}

    def resolve(self,b,data,now=None):
        with server.db() as con:return disputes.resolve(con,b['id'],'operator',data,now or self.start+timedelta(hours=1),'local')

    def test_server_time_ownership_private_evidence_and_disputed_handover_guards(self):
        b=self.act(self.request())
        self.assertEqual(self.read(b,now=self.start+timedelta(minutes=15))['stage'],'contact_reminder')
        self.expect_error(409,lambda:self.report(b,now=self.start+timedelta(minutes=30,microseconds=-1)))
        self.expect_error(404,lambda:self.report(b,user='stranger'))
        case=self.report(b,self.payload(b,image=fixture_image()))
        self.assertEqual(case['bookingStatus'],'disputed')
        self.assertEqual(engine.parse(case['case']['deadline']),self.start+timedelta(minutes=30,hours=48))
        self.assertFalse(self.read(b,user='abc')['items'])
        self.assertEqual(len(self.read(b,user='operator',admin=True)['items']),1)
        with server.db() as con:
            serialized=json.dumps([tuple(r) for r in con.execute('SELECT payload FROM notifications')])
            self.assertNotIn('TEST private evidence',serialized)
            with self.assertRaises(sqlite3.IntegrityError):con.execute("UPDATE dispute_events SET text='changed'")
        blocked={'id':b['id'],'revision':case['bookingRevision']}
        self.expect_error(409,lambda:self.act(blocked,'start','abc',now=self.start+timedelta(hours=1)))
        self.assertTrue(self.read(b,now=self.start+timedelta(hours=49))['case']['overdue'])
        evidence=self.payload(blocked,action='evidence',revision=case['case']['revision'],text='TEST other side')
        self.report(blocked,evidence,user='abc')
        self.assertEqual(self.read(b,user='abc')['items'][0]['text'],'TEST other side')
        self.assertEqual(len(self.read(b)['items']),1)

    def test_parallel_retries_and_adjudications_refund_once_and_count_only_confirmed(self):
        b=self.act(self.request());payload=self.payload(b);gate=threading.Barrier(2)
        def send(_):gate.wait();return self.report(b,payload)
        with ThreadPoolExecutor(max_workers=2) as pool:cases=list(pool.map(send,range(2)))
        self.assertEqual(cases[0]['case'],cases[1]['case'])
        with server.db() as con:self.assertEqual(disputes.review_count(con,'abc',self.start),0)
        decisions=[self.decision(cases[0]),self.decision(cases[0])];gate=threading.Barrier(2)
        def settle(data):
            gate.wait()
            try:return self.resolve(b,data)
            except engine.BookingError as e:return e.status
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(settle,decisions))
        self.assertEqual(sum(isinstance(r,dict) for r in results),1);self.assertIn(409,results)
        winner=next(i for i,r in enumerate(results) if isinstance(r,dict))
        replay=self.resolve(b,decisions[winner])
        self.assertEqual(replay['bookingStatus'],'cancelled');self.assertEqual(replay['case']['refundMinor'],15000000)
        with server.db() as con:
            self.assertEqual(wallet.balance(con,'abc'),100000000)
            self.assertEqual(disputes.review_count(con,'abc',self.start+timedelta(hours=1)),1)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM wallet_entries WHERE kind='commission_refund'").fetchone()[0],1)
        self.expect_error(409,lambda:self.resolve(b,{**decisions[winner],'reason':'Changed'}))

    def test_participant_receipt_keeps_original_evidence_after_resolution(self):
        b=self.act(self.request());data=self.payload(b);created=self.report(b,data)
        receipt=created['acknowledgement']
        self.assertEqual(receipt,{'requestId':data['requestId'],'messageId':created['items'][0]['id'],
            'revision':1,'action':'report','kind':'no_show'})
        self.assertNotIn('acknowledgement',self.read(b))
        self.resolve(b,self.decision(created))
        with server.db() as con:
            before=[tuple(r) for r in con.execute('SELECT * FROM wallet_entries ORDER BY id')]
        replay=self.report(b,data)
        self.assertEqual(replay['acknowledgement'],receipt)
        self.assertEqual(replay['case']['status'],'resolved')
        self.assertFalse(replay['canAddEvidence'])
        with server.db() as con:
            self.assertEqual([tuple(r) for r in con.execute('SELECT * FROM wallet_entries ORDER BY id')],before)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM dispute_events').fetchone()[0],2)
        self.expect_error(409,lambda:self.report(b,{**data,'text':'different'}))
        self.expect_error(404,lambda:self.report(b,data,user='stranger'))

    def test_receipt_never_discloses_opposing_private_evidence(self):
        b=self.act(self.request());created=self.report(b)
        payload=self.payload({'revision':created['bookingRevision']},action='evidence',revision=1,text='TEST opposing private')
        evidence=self.report(b,payload,user='abc')
        self.assertEqual(evidence['acknowledgement']['messageId'],evidence['items'][0]['id'])
        self.assertEqual(evidence['acknowledgement']['revision'],2)
        self.assertNotIn('TEST private evidence',json.dumps(evidence))
        self.assertNotIn('TEST opposing private',json.dumps(self.read(b)))

    def test_notification_failure_rolls_back_resolution_and_money(self):
        b=self.act(self.request());case=self.report(b);data=self.decision(case)
        original=notifications.publish
        def fail(*args):original(*args);raise RuntimeError('TEST database failure')
        with patch.object(notifications,'publish',side_effect=fail):
            with self.assertRaises(RuntimeError):self.resolve(b,data)
        self.assertEqual(self.read(b)['case']['status'],'open')
        with server.db() as con:
            self.assertEqual(wallet.balance(con,'abc'),85000000)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM booking_incidents').fetchone()[0],0)
        self.resolve(b,data)

    def test_active_service_partial_refund_and_unconfirmed_no_show_resume_without_penalty(self):
        b=self.act(self.request());first=self.act(b,'start','customer',now=self.start)
        active=self.act(first,'start','abc',now=self.start)
        self.expect_error(409,lambda:self.report(active))
        case=self.report(active,self.payload(active,kind='service'))
        self.assertEqual(len(self.read(active,admin=True)['handoverConfirmations']),2)
        for invalid in [-1,True,0.5,'5000000',15000001]:
            with self.subTest(refund=invalid):
                with self.assertRaises(ValueError):self.resolve(active,self.decision(case,outcome='cancel_service',fault='none',refundMinor=invalid))
                self.assertEqual(self.read(active)['case']['status'],'open')
                with server.db() as con:
                    self.assertEqual(wallet.balance(con,'abc'),85000000)
                    self.assertEqual(con.execute("SELECT COUNT(*) FROM wallet_entries WHERE kind='commission_refund'").fetchone()[0],0)
        result=self.resolve(active,self.decision(case,outcome='cancel_service',fault='none',refundMinor=5000000))
        self.assertEqual(result['case']['refundMinor'],5000000)
        self.assertFalse(result['customerServicePaymentRefunded'])
        next_b=self.act(self.request(self.quote(start=self.end,end=self.end+timedelta(days=1))))
        next_case=self.report(next_b,now=self.end+timedelta(minutes=30))
        resumed=self.resolve(next_b,self.decision(next_case,outcome='continue',fault='none',refundMinor=0),now=self.end+timedelta(hours=1))
        self.assertEqual(resumed['bookingStatus'],'accepted')
        with server.db() as con:self.assertEqual(disputes.review_count(con,'abc',self.end+timedelta(hours=1)),0)

    def test_three_distinct_late_cancellations_emergency_exception_and_exact_30_day_window(self):
        bookings=[];moments=[]
        for index in range(3):
            start=self.start+timedelta(days=index*4)
            b=self.act(self.request(self.quote(start=start,end=start+timedelta(days=1))))
            moment=start-timedelta(hours=1);moments.append(moment)
            cancelled=self.act(b,'cancel','abc',now=moment);bookings.append(cancelled)
        current=moments[-1]
        with server.db() as con:
            self.assertEqual(disputes.review_count(con,'abc',current),3)
            self.assertEqual(disputes.review_count(con,'abc',moments[0]+timedelta(days=30)),3)
            self.assertEqual(disputes.review_count(con,'abc',moments[0]+timedelta(days=30,microseconds=1)),2)
        data={'revision':0,'requestId':secrets.token_hex(16),'excused':True,'reason':'TEST verified emergency'}
        with server.db() as con:result=disputes.excuse(con,bookings[0]['id'],'abc','operator',data,current)
        self.assertFalse(result['reviewRequired']);self.assertEqual(result['count30Days'],2)
        with server.db() as con:
            disputes.excuse(con,bookings[0]['id'],'abc','operator',data,current)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM incident_events WHERE booking_id=?',(bookings[0]['id'],)).fetchone()[0],2)
            self.assertEqual(wallet.balance(con,'abc'),100000000)
        self.expect_error(409,lambda:self.excuse_again(bookings[0],{**data,'requestId':secrets.token_hex(16)},current))

    def excuse_again(self,b,data,current):
        with server.db() as con:return disputes.excuse(con,b['id'],'abc','operator',data,current)

    def test_migration_backfills_only_actual_accepted_late_cancellations_at_microsecond_edge(self):
        ids=[]
        for index,extra in enumerate([1,0,-1]):
            start=self.start+timedelta(days=index*4)
            b=self.act(self.request(self.quote(start=start,end=start+timedelta(days=1))))
            ids.append(b['id']);self.act(b,'cancel','abc',now=start-timedelta(hours=24,microseconds=extra))
        # Exercise the historical upgrade with a real version-16 prefix.
        # Copy only the immutable inputs and their required parent records.
        source=server.DATA/'momiq.sqlite3'
        release=migrations.MIGRATIONS
        with patch.object(server,'DATA',server.DATA/'pre17'):
            with patch.object(migrations,'MIGRATIONS',release[:16]):server.setup()
            with server.db() as con:
                con.execute('ATTACH DATABASE ? AS fixture',(str(source),))
                for table in ('users','booking_quotes','bookings','booking_events'):
                    con.execute(f'INSERT INTO main.{table} SELECT * FROM fixture.{table}')
                con.commit()
                con.execute('DETACH DATABASE fixture')
                with patch.object(migrations,'MIGRATIONS',release[:17]):
                    self.assertEqual(migrations.migrate(con),[17])
                rows=con.execute('SELECT booking_id FROM booking_incidents').fetchall()
                self.assertEqual([r[0] for r in rows],[ids[-1]])


class DisputeHttpTests(unittest.TestCase):
    setUp=test_booking_http.BookingHttpTests.setUp
    save=test_booking_http.BookingHttpTests.save
    review=test_booking_http.BookingHttpTests.review
    stop_http=test_booking_http.BookingHttpTests.stop_http
    req=test_booking_http.BookingHttpTests.req
    quote=test_booking_http.BookingHttpTests.quote
    book=test_booking_http.BookingHttpTests.book
    admin=test_support_tickets.SupportTests.admin

    def test_authenticated_routes_private_images_admin_decision_and_incident_history(self):
        b=self.book();b=self.req('/api/bookings/'+b['id']+'/accept','POST',{'revision':b['revision'],'requestId':secrets.token_hex(16)},user='abc')
        path='/api/bookings/'+b['id']+'/dispute';admin_path='/api/admin/disputes/'+b['id']
        with patch.object(disputes,'datetime') as clock:
            clock.now.return_value=engine.parse(b['snapshot']['startsAt'])+timedelta(minutes=31)
            data={'action':'report','kind':'no_show','revision':0,'bookingRevision':b['revision'],'text':'TEST private complaint','image':fixture_image(),'requestId':secrets.token_hex(16)}
            case=self.req(path,'POST',data)
            self.req(path,user='stranger',status=404)
            self.req(admin_path,status=401)
            self.assertEqual(self.req(path,user='abc')['items'],[])
            image=path+'/evidence/'+case['items'][0]['id']+'/image'
            self.req(image,user='abc',status=404)
            self.assertEqual(self.req(image)['image'],fixture_image())
            admin_image=admin_path+'/evidence/'+case['items'][0]['id']+'/image'
            self.assertEqual(self.admin(admin_image)['image'],fixture_image())
            self.admin(admin_path+'/resolve',status=404)
            decision={'revision':1,'bookingRevision':case['bookingRevision'],'outcome':'not_started','fault':'sitter','emergency':False,'refundMinor':case['refundableMinor'],'reason':'TEST admin verified','requestId':secrets.token_hex(16)}
            result=self.admin(admin_path+'/resolve',decision)
            self.assertEqual(result['bookingStatus'],'cancelled')
            appeal={'action':'reply','text':'TEST review request','image':None,'revision':0,
                   'subject':'Decision review','topic':'dispute_appeal','bookingId':b['id'],
                   'appealRevision':result['case']['revision'],'requestId':secrets.token_hex(16)}
            created=self.req('/api/support','POST',appeal,user='abc')
            tid=created['ticket']['id'];ref=created['disputeAppeal']
            self.assertEqual(ref['bookingId'],b['id'])
            self.req('/api/support/'+tid,user='customer',status=404)
            self.assertNotIn('TEST private complaint',json.dumps(created))
            reviewed=self.admin('/api/admin/support/'+tid,{'action':'resolve','text':'TEST decision reviewed',
                'revision':1,'image':None,'requestId':secrets.token_hex(16),'reviewedDisputeEventId':ref['eventId']})
            self.assertEqual(reviewed['ticket']['status'],'resolved')
            self.assertEqual(self.req('/api/support','POST',appeal,user='abc')['acknowledgement'],created['acknowledgement'])
            self.assertEqual(self.req(path,user='abc')['items'][0]['role'],'admin')
            self.assertEqual(self.admin('/api/admin/disputes?status=resolved')['items'][0]['bookingId'],b['id'])
            rows=self.admin('/api/admin/incidents')['items'];self.assertEqual(rows[0]['count30Days'],1)
            history='/api/admin/incidents/'+b['id']+'/abc/history'
            self.assertEqual(len(self.admin(history)['items']),1)
            self.admin('/api/admin/incidents/'+b['id']+'/abc/excuse',{'revision':0,'requestId':secrets.token_hex(16),'excused':True,'reason':'TEST emergency verified'})
            self.assertEqual(len(self.admin(history)['items']),2)
            for suffix in ['?before=0','?status=bad','?x=1']:self.admin('/api/admin/disputes'+suffix,status=400)


if __name__=='__main__':unittest.main()
