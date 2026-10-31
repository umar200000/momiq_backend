import json
import secrets
import sqlite3
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import server
import catalog
import booking_reviews
import support_targets
import support_tickets
import test_support_tickets
import test_booking_reviews


class SupportTargetTests(unittest.TestCase):
    setUp=test_support_tickets.SupportTests.setUp
    save=test_support_tickets.SupportTests.save
    review=test_support_tickets.SupportTests.review
    stop_http=test_support_tickets.SupportTests.stop_http
    req=test_support_tickets.SupportTests.req
    admin=test_support_tickets.SupportTests.admin
    data=test_support_tickets.SupportTests.data
    reply=test_support_tickets.SupportTests.reply

    def report(self,**changes):
        return self.data(topic='safety',target={'kind':'listing','id':'abc:boarding'},**changes)

    def reject_listing(self,reason='TEST original decision'):
        with server.db() as con:
            result=catalog.review(con,'abc','boarding',{'decision':'reject','reason':reason,
                '_revision':catalog.revision(con,'abc'),'testOnly':True},'test-admin','test')
            return result['moderation']['boarding']['appealTarget']

    def test_appeal_requires_owner_current_decision_reason_and_exact_target(self):
        target=self.reject_listing()
        self.req('/api/support','POST',self.data(target=target),status=404)
        self.req('/api/support','POST',self.data(target=target,text=''),user='abc',status=400)
        for bad in ({**target,'revision':1},{**target,'revision':'0'},{**target,'purpose':'report'},
                    {k:v for k,v in target.items() if k!='revision'}):
            self.req('/api/support','POST',self.data(target=bad),user='abc',status=400)
        result=self.req('/api/support','POST',self.data(target=target),user='abc')
        self.assertEqual(result['target']['purpose'],'appeal')
        self.assertEqual(result['target']['snapshot']['reason'],'TEST original decision')
        with server.db() as con:
            self.assertEqual(catalog.document(con,'abc')['moderation']['boarding']['status'],'rejected')
            with self.assertRaisesRegex(Exception,'topilmadi'):support_targets.capture(con,target,'production','abc')
            con.execute("UPDATE listing_moderation SET reason='',reviewed_by=NULL WHERE user_id='abc'")
            self.assertNotIn('appealTarget',catalog.document(con,'abc')['moderation']['boarding'])
        self.req('/api/support','POST',self.data(target=target),user='abc',status=404)

    def test_appeal_retry_keeps_original_decision_after_new_moderation(self):
        target=self.reject_listing();data=self.data(target=target)
        original=self.req('/api/support','POST',data,user='abc')
        newer=self.reject_listing('TEST later decision')
        self.assertNotEqual(target['revision'],newer['revision'])
        self.assertEqual(self.req('/api/support','POST',data,user='abc'),original)
        self.req('/api/support','POST',self.data(target=target),user='abc',status=409)
        self.req('/api/support','POST',{**data,'target':newer},user='abc',status=409)
        updated=self.req('/api/support','POST',self.data(target=newer),user='abc')
        self.assertEqual(updated['target']['snapshot']['reason'],'TEST later decision')
        self.assertEqual(self.req('/api/support/'+original['ticket']['id'],user='abc')['target'],original['target'])

    def test_only_administrator_can_resolve_appeal_without_restoring_source(self):
        created=self.req('/api/support','POST',self.data(target=self.reject_listing()),user='abc')
        path='/api/admin/support/'+created['ticket']['id']
        self.assertTrue(self.admin(path)['canResolve'])
        with server.db() as con:con.execute("UPDATE admin_permissions SET role='support' WHERE username='test-admin'")
        del self.admin_token
        self.assertFalse(self.admin(path)['canResolve'])
        self.admin(path,self.reply(action='resolve'),status=403)
        self.admin(path,self.reply())
        with server.db() as con:con.execute("UPDATE admin_permissions SET role='administrator' WHERE username='test-admin'")
        del self.admin_token
        version=self.admin(path)['decisionContext']['version']
        closed=self.admin(path,self.reply(revision=2,action='resolve',text='TEST reviewed decision',decisionVersion=version))
        self.assertEqual(closed['ticket']['status'],'resolved')
        with server.db() as con:self.assertEqual(catalog.document(con,'abc')['moderation']['boarding']['status'],'rejected')

    def test_public_photo_report_binds_approved_derivative_and_replays_after_hiding(self):
        import base64
        import hashlib
        from test_media import fixture_image
        from media_validation import public_photo
        photo = public_photo(fixture_image())
        with server.db() as con:
            con.execute("UPDATE listing_moderation SET public_media=? WHERE user_id='abc' AND service='boarding'",
                        (json.dumps({'photo':photo, 'homePhotos':[photo]}),))
        digest = hashlib.sha256(base64.b64decode(photo)).hexdigest()
        target = {'kind':'listing','id':'abc:boarding','media':'home:0','sha256':digest}
        data = self.data(target=target)
        for changes,status in [({'sha256':'f'*64},409),({'media':'home:1'},404),
                               ({'media':'passport'},400),({'image':photo},400)]:
            self.req('/api/support','POST',self.data(target={**target,**changes}),status=status)
        saved = self.req('/api/support','POST',data)
        self.assertEqual(saved['target']['snapshot']['media'], {'slot':'home:0','sha256':digest})
        self.assertNotIn(photo,json.dumps(saved))
        self.reject_listing()
        self.assertEqual(self.req('/api/support','POST',data), saved)
        self.req('/api/support','POST',self.data(target=target),status=404)

    def test_public_snapshot_is_server_owned_private_and_survives_source_changes(self):
        created=self.req('/api/support','POST',self.report())
        identity=created['ticket']['id'];target=created['target']
        self.assertEqual(target['kind'],'listing');self.assertEqual(target['id'],'abc:boarding')
        self.assertEqual(set(target['snapshot']),{'name','about','service','price','priceUnit','pets','capacity','years','testOnly','revision'})
        self.assertNotIn('target',self.req('/api/support')['items'][0])
        self.req('/api/support/'+identity,user='stranger',status=404)
        self.assertEqual(self.admin('/api/admin/support/'+identity)['target'],target)
        with server.db() as con:
            original=con.execute("SELECT status FROM listing_moderation WHERE user_id='abc' AND service='boarding'").fetchone()[0]
            self.assertEqual(original,'approved')
            con.execute("UPDATE listing_moderation SET status='suspended' WHERE user_id='abc'")
        self.assertEqual(self.req('/api/support/'+identity)['target'],target)
        self.admin('/api/admin/support/'+identity,self.reply(action='resolve',text='TEST reason'))
        reopened=self.req('/api/support/'+identity,'POST',self.reply(revision=2,text='TEST follow-up'))
        self.assertEqual(reopened['ticket']['status'],'open');self.assertEqual(reopened['target'],target)

    def test_invalid_forged_hidden_or_production_test_targets_leave_no_ticket(self):
        for target in (None,[],{'kind':[],'id':'abc:boarding'}, {'kind':'profile','id':'abc'},
                       {'kind':'listing','id':'abc:boarding','snapshot':{}},
                       {'kind':'review','id':'01'},{'kind':'listing','id':'abc:unknown'}):
            self.req('/api/support','POST',self.data(target=target),status=400)
        self.req('/api/support','POST',self.report(text=''),status=400)
        self.req('/api/support','POST',self.data(target={'kind':'listing','id':'missing:boarding'}),status=404)
        with server.db() as con:
            with self.assertRaisesRegex(Exception,'topilmadi'):
                support_tickets.write(con,'customer',None,self.report(),server.photo,environment='production')
        with server.db() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM support_tickets').fetchone()[0],0)
            self.assertEqual(con.execute('SELECT count(*) FROM support_targets').fetchone()[0],0)

    def test_lost_reply_retry_after_source_hidden_and_changed_target_conflict(self):
        data=self.report();created=self.req('/api/support','POST',data)
        with server.db() as con:con.execute("UPDATE listing_moderation SET status='suspended' WHERE user_id='abc'")
        self.assertEqual(self.req('/api/support','POST',data),created)
        self.req('/api/support','POST',{**data,'target':{'kind':'listing','id':'abc:personal'}},status=409)
        self.req('/api/support','POST',self.report(),status=404)
        self.req('/api/support/'+created['ticket']['id'],'POST',self.reply(target=data['target']),status=400)
        with server.db() as con:self.assertEqual(con.execute('SELECT count(*) FROM support_targets').fetchone()[0],1)

    def test_parallel_retry_captures_once_and_snapshot_cannot_be_overwritten(self):
        data=self.report();gate=threading.Barrier(2)
        def create(_):
            gate.wait()
            with server.db() as con:return support_tickets.write(con,'customer',None,data,server.photo,environment='test')
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(create,range(2)))
        self.assertEqual(results[0],results[1])
        with server.db() as con:
            row=tuple(con.execute('SELECT * FROM support_targets').fetchone())
            for sql,args in [('UPDATE support_targets SET snapshot=?',('{}',)),('DELETE FROM support_targets',()),
                             ('INSERT OR REPLACE INTO support_targets VALUES(?,?,?,?,?)',row)]:
                with self.assertRaises(sqlite3.IntegrityError):con.execute(sql,args)
            self.assertEqual(tuple(con.execute('SELECT * FROM support_targets').fetchone()),row)

    def test_snapshot_write_failure_rolls_back_ticket_message_quota_and_request(self):
        original=support_targets.attach
        def fail(*args):
            original(*args)
            raise RuntimeError('TEST write failure')
        with patch.object(support_targets,'attach',side_effect=fail):
            self.req('/api/support','POST',self.report(),status=500)
        with server.db() as con:
            for table in ('support_tickets','support_targets','support_messages','support_requests'):
                self.assertEqual(con.execute('SELECT count(*) FROM '+table).fetchone()[0],0)
            self.assertEqual(con.execute("SELECT count(*) FROM attempts WHERE key='conversation:support:owner:customer'").fetchone()[0],0)
        self.assertIsNotNone(self.req('/api/support','POST',self.report())['target'])


class ReviewTargetTests(unittest.TestCase):
    setUp=test_booking_reviews.BookingReviewTests.setUp
    save=test_booking_reviews.BookingReviewTests.save
    review=test_booking_reviews.BookingReviewTests.review
    quote=test_booking_reviews.BookingReviewTests.quote
    request=test_booking_reviews.BookingReviewTests.request
    act=test_booking_reviews.BookingReviewTests.act
    accepted=test_booking_reviews.BookingReviewTests.accepted
    active=test_booking_reviews.BookingReviewTests.active
    complete=test_booking_reviews.BookingReviewTests.complete
    write=test_booking_reviews.BookingReviewTests.write
    data=test_booking_reviews.BookingReviewTests.data

    def test_hidden_review_appeal_discloses_reason_only_to_author_and_checks_revision(self):
        b=self.complete();review=self.write(b,self.data())['review'];identity=int(review['id'])
        with server.db() as con:
            booking_reviews.moderate(con,'test-admin',identity,{'hidden':True,'revision':1,
                'requestId':secrets.token_hex(16),'reason':'TEST hidden reason'},self.start)
            owner=booking_reviews.owner_view(con,b['id'],'customer',self.start)
            target=owner['appealTarget']
            self.assertEqual(owner['moderation']['reason'],'TEST hidden reason')
            sitter=booking_reviews.owner_view(con,b['id'],'abc',self.start)
            self.assertIsNone(sitter['moderation']);self.assertIsNone(sitter['appealTarget'])
            snapshot=support_targets.capture(con,target,'test','customer')
            self.assertEqual(snapshot['decision']['revision'],2)
            self.assertNotIn('actor',snapshot['decision'])
            with self.assertRaisesRegex(Exception,'topilmadi'):support_targets.capture(con,target,'test','abc')
            with self.assertRaisesRegex(Exception,'o‘zgargan'):support_targets.capture(con,{**target,'revision':'1'},'test','customer')
            con.commit()
            booking_reviews.moderate(con,'test-admin',identity,{'hidden':False,'revision':2,
                'requestId':secrets.token_hex(16),'reason':'TEST restored'},self.start)
            self.assertIsNone(booking_reviews.owner_view(con,b['id'],'customer',self.start)['appealTarget'])
            with self.assertRaisesRegex(Exception,'topilmadi'):support_targets.capture(con,target,'test','customer')

    def test_review_snapshot_rejects_private_hidden_withdrawn_and_test_content(self):
        b=self.complete();review=self.write(b,self.data())['review']
        target={'kind':'review','id':review['id']}
        with server.db() as con:
            snapshot=support_targets.capture(con,target,'test')
            self.assertEqual(snapshot['text'],review['text'])
            self.assertNotIn('bookingId',snapshot);self.assertNotIn('customerId',snapshot)
            with self.assertRaisesRegex(Exception,'topilmadi'):support_targets.capture(con,target,'production')
            for field in ('hidden','withdrawn'):
                con.execute('UPDATE booking_reviews SET '+field+'=1')
                with self.assertRaisesRegex(Exception,'topilmadi'):support_targets.capture(con,target,'test')
                con.execute('UPDATE booking_reviews SET '+field+'=0')
            con.execute("UPDATE listing_moderation SET status='suspended'")
            with self.assertRaisesRegex(Exception,'topilmadi'):support_targets.capture(con,target,'test')
