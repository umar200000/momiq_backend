from datetime import timedelta
import json
import secrets
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
import threading

import booking_care as care
import server
import test_booking_engine


class BookingCareTests(unittest.TestCase):
    setUp = test_booking_engine.BookingEngineTests.setUp
    save = test_booking_engine.BookingEngineTests.save
    review = test_booking_engine.BookingEngineTests.review
    quote = test_booking_engine.BookingEngineTests.quote
    request = test_booking_engine.BookingEngineTests.request
    act = test_booking_engine.BookingEngineTests.act
    expect_error = test_booking_engine.BookingEngineTests.expect_error

    def accepted(self):
        return self.act(self.request())

    def active(self):
        b = self.accepted()
        b = self.act(b, 'start', user='customer', now=self.start)
        return self.act(b, 'start', now=self.start)

    def payload(self, kind='report', **changes):
        value = {'petId':'cat-a','kind':kind,'day':care.today(self.start) if kind=='report' else '',
                 'category':'food' if kind=='report' else '', 'revision':0,'requestId':secrets.token_hex(16),
                 'payload':{'state':'done','note':'TEST fed'} if kind=='report' else
                 {**{key:'' for key in care.CATEGORIES},'food':'08:00 TEST food','reason':'TEST instruction'}}
        value.update(changes)
        return value

    def write(self,b,data,user='abc',now=None):
        with server.db() as con:
            return care.save(con,b['id'],user,data,now or self.start)

    def read(self,b,user='customer',day=None,now=None):
        with server.db() as con:
            return care.overview(con,b['id'],user,day,now or self.start)

    def test_instructions_do_not_change_agreement_and_history_is_private(self):
        b=self.accepted(); original=json.dumps(b['snapshot'],sort_keys=True)
        self.expect_error(403,lambda:self.write(b,self.payload('instructions')))
        first=self.write(b,self.payload('instructions'),user='customer')
        p=self.payload('instructions',revision=1)
        p['payload']['food']='12:00 TEST changed'
        self.write(b,p,user='customer')
        current=self.read(b,'abc')
        self.assertEqual(current['pets'][0]['instructions']['payload']['food'],'12:00 TEST changed')
        self.assertFalse(current['canReport'])
        with server.db() as con:
            import booking_engine
            self.assertEqual(json.dumps(booking_engine.view(con,b['id'],'abc')['snapshot'],sort_keys=True),original)
            self.assertEqual([e['revision'] for e in care.history(con,b['id'],'abc')['items']],[2,1])
            self.expect_error(404,lambda:care.history(con,b['id'],'stranger'))
        self.expect_error(409,lambda:self.write(b,self.payload('instructions'),user='customer'))
        self.assertEqual(first['actorRole'],'customer')

    def test_reports_roles_date_retry_correction_and_immutable_history(self):
        b=self.active()
        with self.assertRaises(ValueError):
            self.write(b,self.payload(payload={'state':'undone','note':'nothing to undo'}))
        p=self.payload();first=self.write(b,p)
        self.assertEqual(self.write(b,p),first)
        self.assertEqual(self.read(b)['pets'][0]['reports'][0]['payload']['state'],'done')
        self.expect_error(403,lambda:self.write(b,self.payload(),user='customer'))
        self.expect_error(404,lambda:self.write(b,self.payload(),user='stranger'))
        self.expect_error(404,lambda:self.write(b,self.payload(petId='foreign')))
        self.expect_error(403,lambda:self.write(b,self.payload(day=care.today(self.start+timedelta(days=1)))))
        self.expect_error(403,lambda:self.write(b,self.payload(day=care.today(self.start-timedelta(days=1)))))
        self.expect_error(409,lambda:self.write(b,{**p,'payload':{'state':'done','note':'changed'}}))
        correction=self.payload(revision=1,payload={'state':'undone','note':'TEST mistaken tap'})
        self.write(b,correction)
        self.assertEqual(self.read(b)['pets'][0]['reports'][0]['revision'],2)
        with server.db() as con:
            self.assertEqual(len(care.history(con,b['id'],'customer')['items']),2)
            with self.assertRaises(sqlite3.IntegrityError):con.execute('DELETE FROM care_entries')
        with server.db() as con:
            with self.assertRaises(sqlite3.IntegrityError):con.execute("UPDATE care_entries SET payload='{}'")
        with self.assertRaises(ValueError):self.write(b,self.payload(revision=2,payload={'state':'done','note':''}))

    def test_parallel_revision_conflict_and_completed_read_only(self):
        b=self.active(); barrier=threading.Barrier(2)
        def send():
            barrier.wait()
            try:return self.write(b,self.payload())['revision']
            except care.engine.BookingError as error:return error.status
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(lambda _:send(),range(2))),[1,409])
        retry=self.payload(category='water'); saved=self.write(b,retry)
        b=self.act(b,'complete',user='customer',now=self.start+timedelta(hours=1))
        b=self.act(b,'complete',now=self.start+timedelta(hours=1))
        self.assertFalse(self.read(b,'abc')['canReport'])
        self.expect_error(403,lambda:self.write(b,self.payload(category='walk')))
        # A lost response can still be retried after service completion.
        self.assertEqual(self.write(b,retry),saved)
        with server.db() as con:
            self.assertEqual(len(care.history(con,b['id'],'customer')['items']),2)

    def test_tashkent_day_empty_and_bounded_history(self):
        b=self.active()
        self.assertEqual(self.read(b)['pets'][0]['reports'],[])
        boundary=self.start.replace(hour=19,minute=0,second=0,microsecond=0)
        self.assertNotEqual(care.today(boundary),care.today(boundary-timedelta(microseconds=1)))
        for revision in range(32):
            self.write(b,self.payload(revision=revision))
        with server.db() as con:
            page=care.history(con,b['id'],'customer')
            self.assertEqual(len(page['items']),30)
            older=care.history(con,b['id'],'customer',page['nextCursor'])
            self.assertEqual(len(older['items']),2)
            self.assertIsNone(older['nextCursor'])
        for invalid in ['2026-1-1','bad','2026-02-30']:
            with self.assertRaises(ValueError):self.read(b,day=invalid)
        self.expect_error(409,lambda:self.read(self.request()))

    def test_cancelled_history_survives_low_balance_but_blocked_account_cannot_read(self):
        b=self.accepted(); self.write(b,self.payload('instructions'),user='customer')
        b=self.act(b,'cancel',user='customer')
        with server.db() as con:
            con.execute("UPDATE wallet_accounts SET balance_minor=0 WHERE user_id='abc'")
        current=self.read(b,'abc')
        self.assertIsNotNone(current['pets'][0]['instructions'])
        self.assertFalse(current['canReport'])
        self.assertFalse(current['canEditInstructions'])
        self.expect_error(403,lambda:self.write(b,self.payload('instructions',revision=1),user='customer'))
        with server.db() as con:con.execute("UPDATE users SET blocked=1 WHERE id='abc'")
        self.expect_error(403,lambda:self.read(b,'abc'))


if __name__=='__main__':unittest.main()
