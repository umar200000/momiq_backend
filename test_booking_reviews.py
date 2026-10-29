from datetime import timedelta
import json
import secrets
import sqlite3
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import booking_reviews as reviews
import catalog
import server
import test_booking_care
import test_booking_engine


class BookingReviewTests(unittest.TestCase):
    setUp=test_booking_engine.BookingEngineTests.setUp
    save=test_booking_engine.BookingEngineTests.save
    review=test_booking_engine.BookingEngineTests.review
    quote=test_booking_engine.BookingEngineTests.quote
    request=test_booking_engine.BookingEngineTests.request
    act=test_booking_engine.BookingEngineTests.act
    expect_error=test_booking_engine.BookingEngineTests.expect_error
    accepted=test_booking_care.BookingCareTests.accepted
    active=test_booking_care.BookingCareTests.active

    def complete(self):
        b=self.active()
        b=self.act(b,'complete',user='customer',now=self.start+timedelta(hours=1))
        return self.act(b,'complete',now=self.start+timedelta(hours=1))

    def data(self,**changes):
        return {'stars':5,'text':'TEST review','revision':0,'requestId':secrets.token_hex(16),'action':'save',**changes}

    def write(self,b,data,user='customer',now=None):
        with server.db() as con:return reviews.write(con,b['id'],user,data,now or self.start+timedelta(hours=2))

    def test_operator_hidden_review_and_history_reads_require_atomic_private_audit(self):
        b=self.complete();created=self.write(b,self.data())
        identity=int(created['review']['id'])
        with server.db() as con:
            reviews.moderate(con,'test-operator',identity,{'hidden':True,'revision':1,'requestId':secrets.token_hex(16),'reason':'TEST private moderation reason'},self.start)
        routes=[('/api/admin/reviews','review-list-view',{'before':None}),
                (f'/api/admin/reviews/{identity}/history','review-history-view',{'reviewId':identity,'before':None})]
        original=reviews.audit_view
        def fail(*args,**kwargs):
            original(*args,**kwargs)
            raise RuntimeError('TEST audit failure')
        for path,action,target in routes:
            replies=[]
            handler=SimpleNamespace(path=path,command='GET',reply=lambda status,data:replies.append((status,data)))
            with server.db() as con:
                self.assertTrue(reviews.admin_route(handler,con,'test-operator',path,self.start))
            self.assertEqual(replies[0][0],200)
            with server.db() as con:
                row=con.execute('SELECT actor,target FROM audit WHERE action=? ORDER BY id DESC LIMIT 1',(action,)).fetchone()
                self.assertEqual(row['actor'],'test-operator')
                self.assertEqual(json.loads(row['target']),target)
                self.assertNotIn('TEST private',row['target'])
                count=con.execute('SELECT count(*) FROM audit').fetchone()[0]
            replies.clear()
            with patch.object(reviews,'audit_view',side_effect=fail),self.assertRaises(RuntimeError):
                with server.db() as con:reviews.admin_route(handler,con,'test-operator',path,self.start)
            self.assertEqual(replies,[])
            with server.db() as con:
                self.assertEqual(con.execute('SELECT count(*) FROM audit').fetchone()[0],count)
                row=con.execute('SELECT hidden,revision,text FROM booking_reviews WHERE id=?',(identity,)).fetchone()
                self.assertEqual(tuple(row),(1,2,'TEST review'))

    def test_only_customer_of_completed_booking_can_review(self):
        pending=self.request()
        self.expect_error(409,lambda:self.write(pending,self.data()))
        b=self.complete()
        self.expect_error(403,lambda:self.write(b,self.data(),user='abc'))
        self.expect_error(404,lambda:self.write(b,self.data(),user='stranger'))
        for stars in [True,0,6,1.5,'5']:
            with self.assertRaises(ValueError):self.write(b,self.data(stars=stars))
        with self.assertRaises(ValueError):self.write(b,{**self.data(),'testOnly':False})
        result=self.write(b,self.data())
        self.assertTrue(result['review']['testOnly']);self.assertFalse(result['canEdit'])
        self.assertFalse(result['reviewEditable']);self.assertFalse(result['canCreate'])
        with server.db() as con:
            self.assertEqual(reviews.summary(con,'abc','boarding'),{'count':0,'rating':0})
            self.assertEqual(reviews.page(con,'abc','boarding','production')['items'],[])

    def test_parallel_retry_one_review_no_edits_even_immediately(self):
        b=self.complete();data=self.data();barrier=threading.Barrier(2)
        def write():barrier.wait();return self.write(b,data)['review']['id']
        with ThreadPoolExecutor(max_workers=2) as pool:self.assertEqual(len(set(pool.map(lambda _:write(),range(2)))),1)
        self.expect_error(409,lambda:self.write(b,self.data(revision=1,text='changed')))
        self.expect_error(409,lambda:self.write(b,{**data,'stars':1}))
        self.assertEqual(self.write(b,data)['review']['text'],'TEST review')
        with server.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM booking_reviews').fetchone()[0],1)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM review_history').fetchone()[0],1)
            with self.assertRaises(sqlite3.IntegrityError):con.execute("UPDATE booking_reviews SET text='edited'")
        with server.db() as con:
            with self.assertRaises(sqlite3.IntegrityError):con.execute('DELETE FROM review_history')

    def test_withdraw_restore_preserves_text_and_cannot_bypass_moderation(self):
        b=self.complete();self.write(b,self.data())
        withdrawn=self.write(b,self.data(action='withdraw',revision=1))
        self.assertTrue(withdrawn['canRestore']);self.assertTrue(withdrawn['review']['withdrawn'])
        with server.db() as con:
            self.assertEqual(reviews.page(con,'abc','boarding','local')['items'],[])
            reviews.moderate(con,'admin',int(withdrawn['review']['id']),{'hidden':True,'revision':2,'requestId':secrets.token_hex(16),'reason':'TEST moderation'},self.start)
        restored=self.write(b,self.data(action='restore',revision=3))
        self.assertFalse(restored['review']['withdrawn']);self.assertTrue(restored['review']['hidden'])
        self.assertEqual(restored['review']['text'],'TEST review')
        self.expect_error(409,lambda:self.write(b,self.data(action='withdraw',revision=4,text='changed')))
        with server.db() as con:self.assertEqual(reviews.page(con,'abc','boarding','local')['items'],[])

    def test_public_projection_paginates_excludes_test_and_recomputes_visibility(self):
        # Isolated projection fixtures; live APIs still require a completed booking.
        b=self.complete()
        with server.db() as con:
            con.execute('INSERT INTO booking_reviews(booking_id,customer_id,sitter_id,service,author_name,stars,text,test_only,revision,created,updated) VALUES(?,?,?,?,?,?,?,?,1,?,?)',
                        (b['id'],'customer','abc','boarding','TEST author',4,'TEST genuine-projection fixture',0,server.now(),server.now()))
            self.assertEqual(reviews.summary(con,'abc','boarding'),{'count':1,'rating':4})
            item=catalog.profile(con,'local','abc:boarding')
            self.assertEqual((item['reviews'],item['rating']),(1,4))
        for i in range(21):
            with server.db() as con:con.execute('DELETE FROM attempts')
            pending=self.request()
            with server.db() as con:con.execute("UPDATE bookings SET status='completed' WHERE id=?",(pending['id'],))
            self.write(pending,self.data(stars=1))
        with server.db() as con:
            page=reviews.page(con,'abc','boarding','local')
            self.assertEqual(len(page['items']),20)
            self.assertEqual(page['count'],1);self.assertEqual(page['rating'],4)
            item=catalog.profile(con,'local','abc:boarding')
            self.assertEqual((item['reviews'],item['rating']),(1,4))
            older=reviews.page(con,'abc','boarding','local',page['nextCursor'])
            self.assertEqual(len(older['items']),2);self.assertIsNone(older['nextCursor'])
            self.assertTrue(all('customerId' not in r and 'bookingId' not in r for r in page['items']))
            self.assertEqual(len(reviews.page(con,'abc','boarding','production')['items']),1)
            reviews.moderate(con,'admin',1,{'hidden':True,'revision':1,'requestId':secrets.token_hex(16),'reason':'TEST hide'},self.start)
        with server.db() as con:
            self.assertEqual(reviews.summary(con,'abc','boarding')['count'],0)
            item=catalog.profile(con,'local','abc:boarding')
            self.assertEqual((item['reviews'],item['rating']),(0,0))
            con.execute('UPDATE booking_reviews SET hidden=0,withdrawn=1 WHERE id=1')
        with server.db() as con:
            self.assertEqual(catalog.profile(con,'local','abc:boarding')['reviews'],0)
            con.execute('UPDATE booking_reviews SET withdrawn=0 WHERE id=1')
        with server.db() as con:
            self.assertEqual(catalog.profile(con,'local','abc:boarding')['rating'],4)

    def test_moderation_reason_revision_and_retry(self):
        b=self.complete();r=self.write(b,self.data())['review'];key=secrets.token_hex(16)
        data={'hidden':True,'revision':1,'requestId':key,'reason':'TEST reason'}
        with server.db() as con:reviews.moderate(con,'operator',int(r['id']),data,self.start)
        with server.db() as con:reviews.moderate(con,'operator',int(r['id']),data,self.start)
        with server.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM review_history').fetchone()[0],2)
            self.expect_error(409,lambda:reviews.moderate(con,'operator',int(r['id']),{**data,'hidden':False},self.start))
        with server.db() as con:
            with self.assertRaises(ValueError):reviews.moderate(con,'operator',int(r['id']),{**data,'reason':''},self.start)


if __name__=='__main__':unittest.main()
