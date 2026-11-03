from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import unittest
from unittest.mock import patch

import booking_worker
import notifications
import server
import test_booking_engine as fixtures


class ReminderTests(unittest.TestCase):
    setUp=fixtures.BookingEngineTests.setUp
    save=fixtures.BookingEngineTests.save
    review=fixtures.BookingEngineTests.review
    quote=fixtures.BookingEngineTests.quote
    request=fixtures.BookingEngineTests.request
    act=fixtures.BookingEngineTests.act

    def notices(self):
        with server.db() as con:
            return [json.loads(r[0]) for r in con.execute("SELECT payload FROM notifications WHERE source_key LIKE 'booking-reminder:%' ORDER BY id")]

    def tick(self, minutes):
        return booking_worker.run_once(server.db,'local',now=self.start+timedelta(minutes=minutes),batch_size=1)

    def test_exact_boundaries_restart_and_no_money_or_status_change(self):
        booking=self.act(self.request())
        with server.db() as con:
            before=con.execute('SELECT COUNT(*) FROM wallet_entries').fetchone()[0]
        self.assertEqual(self.tick(14.999),0)
        self.assertEqual(self.tick(15),1)
        self.assertEqual(self.tick(29.999),0)
        self.assertEqual(self.tick(30),1)
        self.assertEqual(self.tick(60),0)
        notices=self.notices()
        self.assertEqual([n['status'] for n in notices],['contact_reminder']*2+['complaint_available']*2)
        self.assertTrue(all(n['kind']=='booking' and n['targetId']==booking['id'] for n in notices))
        with server.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM wallet_entries').fetchone()[0],before)
            self.assertEqual(con.execute('SELECT status,revision FROM bookings').fetchone()[:],('accepted',1))
            self.assertEqual(con.execute('SELECT COUNT(*) FROM booking_incidents').fetchone()[0],0)

    def test_late_restart_suppresses_stale_contact_and_concurrent_ticks_deduplicate(self):
        self.act(self.request())
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.tick(31),range(2)))
        self.assertEqual(sum(results),1)
        self.assertEqual([n['status'] for n in self.notices()],['complaint_available']*2)

    def test_transaction_failure_rolls_back_both_notices_then_retries(self):
        self.act(self.request())
        publish=notifications.publish
        calls=[]
        def fail_second(*args):
            calls.append(1)
            if len(calls)==2:raise RuntimeError('TEST second recipient failure')
            return publish(*args)
        with patch.object(notifications,'publish',side_effect=fail_second):
            with self.assertRaises(RuntimeError):self.tick(15)
        self.assertEqual(self.notices(),[])
        self.assertEqual(self.tick(15),1)
        self.assertEqual(len(self.notices()),2)

    def test_active_care_has_no_no_show_alert(self):
        booking=self.act(self.request())
        first=self.act(booking,'start',now=self.start)
        self.act(first,'start',user='customer',now=self.start)
        self.assertEqual(self.tick(30),0)
        self.assertEqual(self.notices(),[])
