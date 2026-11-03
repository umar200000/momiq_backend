from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import secrets
import sqlite3
import unittest
from unittest.mock import patch
import booking_worker
import notifications
import server
import test_booking_care as fixtures
import video_followup as followup


class VideoFollowupTests(unittest.TestCase):
    setUp=fixtures.BookingCareTests.setUp
    save=fixtures.BookingCareTests.save
    review=fixtures.BookingCareTests.review
    quote=fixtures.BookingCareTests.quote
    request=fixtures.BookingCareTests.request
    act=fixtures.BookingCareTests.act
    active=fixtures.BookingCareTests.active
    accepted=fixtures.BookingCareTests.accepted
    expect_error=fixtures.BookingCareTests.expect_error

    def tick(self,hours):
        return booking_worker.run_once(server.db,'local',now=self.start+timedelta(hours=hours),batch_size=2)

    def notices(self):
        with server.db() as con:return [(r['user_id'],json.loads(r['payload'])) for r in con.execute("SELECT * FROM notifications WHERE source_key LIKE 'video-followup:%' ORDER BY id")]

    def data(self,**changes):
        return dict({'petId':'cat-a','day':self.start.date().isoformat(),'slot':'evening','reason':'PRIVATE emergency detail','emergency':True,'requestId':secrets.token_hex(16)},**changes)

    def explain(self,b,data,user='abc',hours=5):
        with server.db() as con:return followup.explain(con,b['id'],user,data,self.start+timedelta(hours=hours))

    def test_exact_deadlines_and_parallel_restart_without_financial_effect(self):
        b=self.active() # 17:00 Toshkent; evening deadline 22:00.
        with server.db() as con:before=con.execute('SELECT COUNT(*) FROM wallet_entries').fetchone()[0]
        self.tick(4.49999);self.assertEqual(self.notices(),[])
        self.tick(4.5);self.assertEqual([(u,n['status']) for u,n in self.notices()],[('abc','video_reminder')])
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lambda _:self.tick(5),range(2)))
        self.assertEqual([(u,n['status']) for u,n in self.notices()],[('abc','video_reminder'),('abc','video_missing'),('customer','video_missing')])
        self.tick(5.1);self.assertEqual(len(self.notices()),3)
        with server.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM wallet_entries').fetchone()[0],before)
            self.assertEqual(con.execute('SELECT status FROM bookings WHERE id=?',(b['id'],)).fetchone()[0],'active')
            self.assertEqual(con.execute('SELECT COUNT(*) FROM booking_incidents').fetchone()[0],0)

    def test_late_restart_skips_stale_reminder_and_transaction_failure_retries(self):
        self.active();publish=notifications.publish;calls=[]
        def fail(*args):
            calls.append(1)
            if len(calls)==2:raise RuntimeError('TEST notice failure')
            publish(*args)
        with patch.object(notifications,'publish',side_effect=fail):
            with self.assertRaises(RuntimeError):self.tick(5)
        self.assertEqual(self.notices(),[])
        self.tick(5)
        self.assertEqual([n['status'] for _,n in self.notices()],['video_missing']*2)

    def test_delivered_video_suppresses_both_alerts(self):
        b=self.active();day=self.start.date().isoformat()
        with server.db() as con:
            con.execute('INSERT INTO booking_videos VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',('a'*32,b['id'],'cat-a',day,'evening','abc','request','hash',10000,100,128,96,'hash','poster',self.start.isoformat()))
        self.tick(4.5);self.tick(5);self.assertEqual(self.notices(),[])
        self.expect_error(409,lambda:self.explain(b,self.data()))

    def test_explanation_private_immutable_retry_and_ownership(self):
        b=self.active();data=self.data()
        self.expect_error(409,lambda:self.explain(b,data,hours=4.99))
        self.expect_error(403,lambda:self.explain(b,data,user='customer'))
        self.expect_error(404,lambda:self.explain(b,data,user='stranger'))
        self.expect_error(409,lambda:self.explain(b,self.data(petId='cat-b')))
        first=self.explain(b,data)
        self.assertEqual(first['requestId'],data['requestId'])
        self.assertEqual(first['bookingId'],b['id'])
        self.assertEqual(first['reason'],data['reason'])
        self.assertTrue(first['emergency'])
        self.assertEqual(first,self.explain(b,data,hours=10))
        self.expect_error(409,lambda:self.explain(b,dict(data,reason='changed')))
        self.expect_error(409,lambda:self.explain(b,self.data()))
        with server.db() as con:
            result=followup.overview(con,b['id'],'customer',data['day'],self.start+timedelta(hours=5),'customer')
            self.assertFalse(result[0]['canExplain']);self.assertTrue(result[0]['explanations'][0]['emergency'])
            notice=con.execute("SELECT payload FROM notifications WHERE source_key LIKE 'video-explanation:%'").fetchone()[0]
            self.assertNotIn('PRIVATE',notice)
            with self.assertRaises(sqlite3.IntegrityError):con.execute("UPDATE video_explanations SET reason='changed'")

    def test_explanation_notice_failure_rolls_back_then_retry(self):
        b=self.active();data=self.data()
        with patch.object(notifications,'publish',side_effect=RuntimeError('TEST fail')):
            with self.assertRaises(RuntimeError):self.explain(b,data)
        with server.db() as con:self.assertEqual(con.execute('SELECT COUNT(*) FROM video_explanations').fetchone()[0],0)
        self.explain(b,data)

    def test_early_completion_skips_future_windows_and_backfill_is_replay_safe(self):
        b=self.active()
        b=self.act(b,'complete',now=self.start+timedelta(minutes=30))
        self.act(b,'complete',user='customer',now=self.start+timedelta(minutes=30))
        with server.db() as con:
            con.execute('DELETE FROM video_checks');con.execute('DELETE FROM video_schedules')
        self.tick(5);self.assertEqual(self.notices(),[])
        self.tick(29);self.assertEqual(self.notices(),[])
        with server.db() as con:self.assertEqual(con.execute('SELECT COUNT(*) FROM video_schedules').fetchone()[0],1)

    def test_no_morning_obligation_before_actual_activation(self):
        b=self.active()
        with server.db() as con:
            rows=con.execute('SELECT slot FROM video_checks WHERE booking_id=? AND day=?',(b['id'],self.start.date().isoformat())).fetchall()
            self.assertEqual([r[0] for r in rows],['evening'])


if __name__=='__main__':unittest.main()
