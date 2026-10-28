import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import secrets
import sqlite3
import threading
import unittest
from unittest.mock import patch

import booking_engine as engine
import catalog
import server
import test_catalog
import wallet
import notifications
import booking_worker


class BookingEngineTests(unittest.TestCase):
    save = test_catalog.CatalogTests.save
    review = test_catalog.CatalogTests.review

    def setUp(self):
        test_catalog.CatalogTests.setUp(self)
        self.save(); self.review()
        self.now = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
        self.start = self.now + timedelta(days=3)
        self.end = self.start + timedelta(days=3)
        with server.db() as con:
            for index, user in enumerate(('customer', 'other', 'stranger')):
                account = server.default_account()
                account['profile'].update(first='TEST', last=user)
                account['pets'] = [{'id': 'cat-a', 'type': 'Mushuk', 'name': user+' cat', 'notes': 'TEST care'},
                                   {'id': 'cat-b', 'type': 'Mushuk', 'name': 'TEST second cat'}]
                con.execute('INSERT INTO users VALUES(?,?,?,0,?)', (user, f'99890000000{index}', json.dumps(account), server.now()))
                con.execute("INSERT INTO user_roles VALUES(?,'customer')", (user,))
            con.execute("UPDATE wallet_accounts SET balance_minor=100000000 WHERE user_id='abc'")

    def quote(self, user='customer', pets=None, start=None, end=None, listing='abc:boarding', **kwargs):
        with server.db() as con:
            return engine.prepare_quote(con, user, listing, pets or ['cat-a'],
                (start or self.start).isoformat(), (end or self.end).isoformat(),
                policy=engine.DailyPolicy(), environment=kwargs.pop('environment', 'local'), now=self.now, **kwargs)

    def request(self, quote=None, user='customer', request=None, now=None):
        if quote is None: quote = self.quote(user)
        with server.db() as con:
            return engine.request_booking(con, user, quote['id'], request or secrets.token_hex(16), environment='local', now=now or self.now)

    def act(self, booking, action='accept', user='abc', request=None, revision=None, now=None, reason=None):
        with server.db() as con:
            return engine.act(con, user, booking['id'], action, booking['revision'] if revision is None else revision,
                              request or secrets.token_hex(16), environment='local', now=now or self.now,
                              reason=reason if reason is not None else ('' if action == 'accept' else 'TEST reason'))

    def expect_error(self, code, callback):
        with self.assertRaises(engine.BookingError) as caught: callback()
        self.assertEqual(caught.exception.status, code)

    def test_server_price_frozen_agreement_and_private_address(self):
        quote = self.quote(pets=['cat-a', 'cat-b'])
        price = quote['snapshot']['price']
        self.assertEqual(price['service_total_minor'], 300000000)
        self.assertEqual(price['commission_minor'], 30000000)
        self.assertNotIn('PRIVATE STREET', json.dumps(quote))
        booking = self.request(quote)
        with server.db() as con:
            con.execute('INSERT INTO platform_settings(version,commission_bps,test_only,actor,reason,created) VALUES(2,2000,1,?,?,?)', ('admin', 'TEST new percentage', server.now()))
            account = json.loads(con.execute("SELECT account FROM users WHERE id='customer'").fetchone()[0])
            account['pets'][0]['name'] = 'CHANGED'
            con.execute("UPDATE users SET account=? WHERE id='customer'", (json.dumps(account),))
        accepted = self.act(booking)
        self.assertEqual(accepted['snapshot']['price'], price)
        self.assertEqual(accepted['snapshot']['pets'][0]['name'], 'customer cat')
        self.assertIn('PRIVATE STREET', json.dumps(accepted))
        with server.db() as con:
            self.assertEqual(wallet.balance(con, 'abc'), 70000000)
            self.assertEqual([x['action'] for x in engine.view(con, booking['id'], 'customer')['history']], ['request', 'accept'])
        self.assertEqual(self.quote()['snapshot']['price']['commission_bps'], 2000)

    def test_request_retry_quote_reuse_and_foreign_ownership(self):
        quote = self.quote(); key = secrets.token_hex(16)
        booking = self.request(quote, request=key)
        self.assertEqual(self.request(quote, request=key)['id'], booking['id'])
        self.assertEqual(self.request(quote)['id'], booking['id'])
        different = self.quote()
        self.expect_error(409, lambda: self.request(different, request=key))
        self.expect_error(404, lambda: self.request(quote, user='other'))
        with server.db() as con:
            self.expect_error(404, lambda: engine.view(con, booking['id'], 'stranger'))
            self.assertEqual(con.execute('SELECT COUNT(*) FROM bookings').fetchone()[0], 1)
        self.expect_error(403, lambda: self.act(booking, user='customer'))
        self.expect_error(404, lambda: self.act(booking, user='stranger'))

    def test_booking_notices_are_atomic_and_never_duplicate_on_retry(self):
        booking=self.request(); identity=booking['id']; source='booking:'+identity+':%'
        original=notifications.publish
        def fail_after_insert(*args):
            original(*args)
            raise RuntimeError('TEST notice storage failure')
        with patch.object(notifications,'publish',side_effect=fail_after_insert):
            with self.assertRaises(RuntimeError): self.act(booking)
        with server.db() as con:
            self.assertEqual(wallet.balance(con,'abc'),100000000)
            self.assertEqual(engine.view(con,identity,'customer')['status'],'pending')
            self.assertEqual(con.execute('SELECT COUNT(*) FROM notifications WHERE source_key LIKE ?',(source,)).fetchone()[0],2)
        key=secrets.token_hex(16)
        accepted=self.act(booking,request=key)
        self.act(booking,request=key)
        key=secrets.token_hex(16)
        self.act(accepted,'cancel',user='customer',request=key)
        self.act(accepted,'cancel',user='customer',request=key)
        with server.db() as con:
            rows=con.execute('SELECT user_id,payload FROM notifications WHERE source_key LIKE ? ORDER BY id',(source,)).fetchall()
            self.assertEqual(len(rows),6)
            for user in ['customer','abc']:
                self.assertEqual([json.loads(r['payload'])['status'] for r in rows if r['user_id']==user],['pending','accepted','cancelled'])
            self.assertEqual(wallet.balance(con,'abc'),100000000)

    def test_expiry_worker_drains_bounded_batches_without_client_requests(self):
        for _ in range(12): self.request()
        due=self.now+timedelta(hours=2)
        self.assertEqual(booking_worker.run_once(server.db,'local',now=due,batch_size=5,max_batches=2),10)
        self.assertEqual(booking_worker.run_once(server.db,'local',now=due,batch_size=5,max_batches=2),2)
        self.assertEqual(booking_worker.run_once(server.db,'local',now=due),0)
        self.expect_error(503,lambda:booking_worker.run_once(server.db,'production',now=due))
        with server.db() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM bookings WHERE status='expired'").fetchone()[0],12)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM booking_events WHERE action='expire'").fetchone()[0],12)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM notifications WHERE source_key LIKE 'booking:%'").fetchone()[0],48)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM wallet_entries WHERE kind='commission'").fetchone()[0],0)

    def test_parallel_accept_same_request_charges_exactly_once(self):
        booking = self.request(); key = secrets.token_hex(16); barrier = threading.Barrier(2)
        def accept(_):
            barrier.wait()
            return self.act(booking, request=key)
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(accept, range(2)))
        self.assertEqual([r['revision'] for r in results], [1, 1])
        with server.db() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM wallet_entries WHERE kind='commission'").fetchone()[0], 1)
            self.assertEqual(wallet.balance(con, 'abc'), 85000000)
        self.expect_error(409, lambda: self.act(booking))
        self.expect_error(409, lambda: self.act(booking, request=key, reason='different'))

    def test_parallel_last_capacity_and_balance_cannot_be_overspent(self):
        first = self.request(self.quote(pets=['cat-a', 'cat-b']))
        second = self.request(user='other')
        barrier = threading.Barrier(2)
        def accept(booking):
            barrier.wait()
            try: return self.act(booking)['status']
            except engine.BookingError as error: return error.status
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(accept, [first, second]))
        self.assertCountEqual(results, ['accepted', 409])
        with server.db() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM wallet_entries WHERE kind='commission'").fetchone()[0], 1)
        # Distinct, non-overlapping intervals compete only on the same balance.
        third = self.request(self.quote(start=self.start+timedelta(days=5), end=self.end+timedelta(days=5)))
        fourth = self.request(self.quote(user='other', start=self.start+timedelta(days=10), end=self.end+timedelta(days=10)), user='other')
        with server.db() as con: con.execute("UPDATE wallet_accounts SET balance_minor=20000000 WHERE user_id='abc'")
        barrier = threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(accept, [third, fourth]))
        self.assertCountEqual(results, ['accepted', 409])
        with server.db() as con: self.assertEqual(wallet.balance(con, 'abc'), 5000000)

    def test_failed_history_write_rolls_back_debit_status_and_retry_record(self):
        booking = self.request(); key = secrets.token_hex(16)
        with server.db() as con:
            con.execute("CREATE TRIGGER injected_failure BEFORE INSERT ON booking_events WHEN NEW.action='accept' BEGIN SELECT RAISE(ABORT, 'TEST disk/write failure'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.act(booking, request=key)
        with server.db() as con:
            self.assertEqual(wallet.balance(con, 'abc'), 100000000)
            self.assertEqual(engine.view(con, booking['id'], 'abc')['status'], 'pending')
            self.assertEqual(con.execute('SELECT COUNT(*) FROM wallet_entries').fetchone()[0], 0)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM booking_requests WHERE request_id=?', (key,)).fetchone()[0], 0)
            con.execute('DROP TRIGGER injected_failure')
        self.assertEqual(self.act(booking, request=key)['status'], 'accepted')

    def test_cancel_refund_once_releases_capacity_and_preserves_history(self):
        booking = self.act(self.request(self.quote(pets=['cat-a', 'cat-b'])))
        pending = self.request(user='other')
        self.expect_error(409, lambda: self.act(pending))
        key = secrets.token_hex(16)
        result = self.act(booking, 'cancel', 'customer', request=key)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(self.act(booking, 'cancel', 'customer', request=key)['revision'], 2)
        self.assertNotIn('PRIVATE STREET', json.dumps(result))
        self.expect_error(409, lambda: self.act(result, 'cancel', 'customer'))
        with server.db() as con:
            self.assertEqual(wallet.balance(con, 'abc'), 100000000)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM wallet_entries WHERE kind='commission_refund'").fetchone()[0], 1)
        self.assertEqual(self.act(pending)['status'], 'accepted')

    def test_deadline_expiry_restart_and_prestart_only_automatic_refund(self):
        booking = self.request()
        due = self.now+timedelta(hours=2)
        self.assertEqual(self.act(booking, now=due)['status'], 'expired')
        another = self.request()
        server.setup()  # Restart/bootstrap preserves pending deadlines.
        with server.db() as con: self.assertEqual(engine.expire_due(con, environment='local', now=due), 1)
        with server.db() as con: self.assertEqual(engine.expire_due(con, environment='local', now=due), 0)
        with server.db() as con:
            self.assertEqual(engine.view(con, another['id'], 'abc')['status'], 'expired')
            self.assertEqual(con.execute('SELECT COUNT(*) FROM wallet_entries').fetchone()[0], 0)
        accepted = self.act(self.request())
        self.expect_error(409, lambda: self.act(accepted, 'cancel', 'customer', now=self.start))
        with server.db() as con: self.assertEqual(wallet.balance(con, 'abc'), 85000000)

    def test_quote_time_customer_pets_and_production_guards(self):
        quote = self.quote()
        self.expect_error(409, lambda: self.request(quote, now=self.now+timedelta(minutes=10)))
        self.expect_error(404, lambda: self.quote(pets=['not-owned']))
        self.expect_error(503, lambda: self.quote(environment='production'))
        self.expect_error(503, lambda: self.quote(environment='staging'))
        with server.db() as con:
            con.execute("UPDATE runtime_metadata SET value='production' WHERE key='environment'")
        self.expect_error(503, self.quote)
        with server.db() as con: con.execute("UPDATE runtime_metadata SET value='local' WHERE key='environment'")
        with self.assertRaises(ValueError): self.quote(start=self.now)
        with self.assertRaises(ValueError): self.quote(address={'address': 'FORGED'})
        with self.assertRaises(ValueError): self.quote(pets=['cat-a', 'cat-a'])

    def test_snapshot_history_and_identity_cannot_be_rewritten(self):
        booking = self.request()
        statements = ["UPDATE booking_quotes SET snapshot='{}'", 'DELETE FROM booking_quotes',
                      "UPDATE booking_events SET reason='changed'", 'DELETE FROM booking_events',
                      "UPDATE bookings SET customer_id='other'"]
        for statement in statements:
            with self.assertRaises(sqlite3.IntegrityError):
                with server.db() as con: con.execute(statement)
        with server.db() as con: self.assertEqual(engine.view(con, booking['id'], 'customer')['revision'], 0)

    def test_peak_capacity_and_half_open_intervals(self):
        # Two existing animals occupy different halves, not two places all day.
        split = self.start+timedelta(hours=2)
        finish = split+timedelta(hours=2)
        a = self.request(self.quote(user='other', start=self.start, end=split), user='other')
        b = self.request(self.quote(user='other', start=split, end=finish), user='other')
        self.act(a); self.act(b)
        candidate = self.request(self.quote(start=self.start, end=finish))
        self.assertEqual(self.act(candidate)['status'], 'accepted')

    def test_same_pet_cannot_be_accepted_by_two_sitters(self):
        with server.db() as con:
            con.execute('INSERT INTO users VALUES(?,?,?,0,?)', ('second', '998911111111', json.dumps(self.account), server.now()))
            con.execute("INSERT INTO user_roles VALUES('second','sitter')")
            con.execute("INSERT INTO wallet_accounts VALUES('second',100000000)")
        with server.db() as con: catalog.save(con, 'second', self.listing, 0)
        with server.db() as con: catalog.review(con, 'second', 'boarding', {'decision':'approve','reason':'TEST','testOnly':True,'_revision':1}, 'admin', 'local')
        first = self.request(); second = self.request(self.quote(listing='second:boarding'))
        self.act(first)
        self.expect_error(409, lambda: self.act(second, user='second'))
        with server.db() as con: self.assertEqual(wallet.balance(con, 'second'), 100000000)

    def test_personal_capacity_and_cross_service_conflict(self):
        data = copy.deepcopy(self.listing)
        data['listings'].append(dict(data['listings'][0], type='personal', capacity=None))
        self.save(data, revision=2)
        with server.db() as con: catalog.review(con, 'abc', 'personal', {'decision':'approve','reason':'TEST','testOnly':True,'_revision':3}, 'admin', 'local')
        self.expect_error(409, lambda: self.quote(pets=['cat-a','cat-b'], listing='abc:personal'))
        personal = self.request(self.quote(listing='abc:personal'))
        boarding = self.request(user='other')
        self.act(personal)
        self.expect_error(409, lambda: self.act(boarding))
        with server.db() as con: self.assertEqual(wallet.balance(con, 'abc'), 85000000)

    def test_dashboard_active_care_overdue_and_tashkent_midnight(self):
        import sitter_dashboard
        start=self.start.replace(hour=19,minute=0,second=0,microsecond=0)
        booking=self.act(self.request(self.quote(start=start,end=start+timedelta(hours=2))))
        with server.db() as con:
            before=sitter_dashboard.overview(con,'abc',start-timedelta(microseconds=1))
        self.assertEqual(before['today']['items'],[])
        with server.db() as con:
            today=sitter_dashboard.overview(con,'abc',start)
        self.assertEqual(today['localDate'],(start+timedelta(hours=5)).date().isoformat())
        self.assertEqual(today['today']['items'][0]['id'],booking['id'])
        booking=self.act(booking,'start','abc',now=start)
        booking=self.act(booking,'start','customer',now=start)
        with server.db() as con:
            active=sitter_dashboard.overview(con,'abc',start+timedelta(days=1))
        self.assertEqual(active['activePetCount'],1)
        self.assertEqual(active['activeBookingCount'],1)
        self.assertTrue(active['today']['items'][0]['overdue'])

    def test_dashboard_bounded_upcoming_and_expired_pending_exclusion(self):
        import sitter_dashboard
        expected=[]
        for i in range(7):
            start=self.start+timedelta(days=i*4)
            expected.append(self.act(self.request(self.quote(start=start,end=start+timedelta(days=1))))['id'])
        unanswered=self.request(self.quote(start=self.start+timedelta(days=40),end=self.start+timedelta(days=41)))
        with server.db() as con:
            data=sitter_dashboard.overview(con,'abc',self.now+timedelta(hours=3))
            self.assertEqual(engine.view(con,unanswered['id'],'abc')['status'],'pending')
        self.assertEqual(data['pendingCount'],0)
        self.assertEqual([b['id'] for b in data['upcoming']['items']],expected[:5])
        self.assertTrue(data['upcoming']['hasMore'])

    def test_parallel_home_visits_and_cross_service_limits(self):
        data=copy.deepcopy(self.listing)
        data['listings'].append(dict(data['listings'][0],type='homeVisit',capacity=None,location=None))
        self.save(data,revision=2)
        with server.db() as con:
            catalog.review(con,'abc','homeVisit',{'decision':'approve','reason':'TEST','testOnly':True,'_revision':3},'admin','local')
            for user in ('customer','other'):
                account=json.loads(con.execute('SELECT account FROM users WHERE id=?',(user,)).fetchone()[0])
                account['addresses']=[{'id':'home','address':'TEST only','lat':41.3,'lon':69.2}]
                con.execute('UPDATE users SET account=? WHERE id=?',(json.dumps(account),user))
        visits=[self.request(self.quote(user=u,listing='abc:homeVisit',address='home'),user=u) for u in ('customer','other')]
        barrier=threading.Barrier(2)
        def accept(booking):
            barrier.wait()
            try: return self.act(booking)['status']
            except engine.BookingError as e: return e.status
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(accept,visits))
        self.assertCountEqual(results,['accepted',409])
        # A different customer and service cannot bypass the visit reservation.
        boarding=self.request(self.quote(user='stranger'),user='stranger')
        self.expect_error(409,lambda:self.act(boarding))
        with server.db() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM wallet_entries WHERE kind='commission'").fetchone()[0],1)
        # Half-open boundary permits the next visit after the previous ends.
        next_visit=self.request(self.quote(listing='abc:homeVisit',address='home',start=self.end,end=self.end+timedelta(days=1)))
        self.assertEqual(self.act(next_visit)['status'],'accepted')

    def test_block_low_balance_rejected_pending_cancel_have_no_fee(self):
        booking = self.request()
        with server.db() as con: con.execute("UPDATE wallet_accounts SET balance_minor=1499999 WHERE user_id='abc'")
        self.expect_error(409, self.quote)
        self.expect_error(409, lambda: self.act(booking))
        self.assertEqual(self.act(booking, 'reject')['status'], 'rejected')
        with server.db() as con: con.execute("UPDATE wallet_accounts SET balance_minor=100000000 WHERE user_id='abc'")
        pending = self.request()
        self.assertEqual(self.act(pending, 'cancel', 'customer')['status'], 'cancelled')
        with server.db() as con: self.assertEqual(con.execute('SELECT COUNT(*) FROM wallet_entries').fetchone()[0], 0)
        quote = self.quote()
        with server.db() as con: con.execute("INSERT INTO chat_blocks VALUES('abc','customer',1,1,?)", (server.now(),))
        self.expect_error(409, lambda: self.request(quote))

    def test_parallel_cancel_and_accept_never_orphans_commission(self):
        booking = self.request(); barrier = threading.Barrier(2)
        def race(action):
            barrier.wait()
            try:
                return self.act(booking, action, 'abc' if action == 'accept' else 'customer')['status']
            except engine.BookingError as error:
                return error.status
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(race, ['accept', 'cancel']))
        self.assertIn(409, results)
        with server.db() as con:
            state = engine.view(con, booking['id'], 'customer')
            charged = con.execute("SELECT COALESCE(SUM(amount_minor),0) FROM wallet_entries").fetchone()[0]
            self.assertEqual(charged, -15000000 if state['status'] == 'accepted' else 0)
            self.assertEqual(wallet.balance(con, 'abc'), 100000000 + charged)

    def test_parallel_refund_and_zero_commission_threshold(self):
        booking = self.act(self.request()); key = secrets.token_hex(16); barrier = threading.Barrier(2)
        def cancel(_):
            barrier.wait()
            return self.act(booking, 'cancel', 'customer', request=key)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(cancel, range(2)))
        self.assertEqual([r['status'] for r in results], ['cancelled', 'cancelled'])
        with server.db() as con:
            self.assertEqual(wallet.balance(con, 'abc'), 100000000)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM wallet_entries WHERE kind='commission_refund'").fetchone()[0], 1)
            con.execute('INSERT INTO platform_settings(version,commission_bps,test_only,actor,reason,created) VALUES(2,0,1,?,?,?)', ('admin', 'TEST zero', server.now()))
        free = self.request()
        with server.db() as con: con.execute("UPDATE wallet_accounts SET balance_minor=1499999 WHERE user_id='abc'")
        self.expect_error(409, lambda: self.act(free))
        with server.db() as con: con.execute("UPDATE wallet_accounts SET balance_minor=1500000 WHERE user_id='abc'")
        self.assertEqual(self.act(free)['status'], 'accepted')
        with server.db() as con:
            self.assertEqual(wallet.balance(con, 'abc'), 1500000)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM wallet_entries').fetchone()[0], 2)

    def test_refund_failure_keeps_accepted_booking_and_original_balance(self):
        booking = self.act(self.request())
        with server.db() as con:
            con.execute("CREATE TRIGGER fail_refund BEFORE INSERT ON booking_events WHEN NEW.action='cancel' BEGIN SELECT RAISE(ABORT, 'TEST failure'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.act(booking, 'cancel', 'customer')
        with server.db() as con:
            self.assertEqual(wallet.balance(con, 'abc'), 85000000)
            self.assertEqual(engine.view(con, booking['id'], 'customer')['status'], 'accepted')
            self.assertEqual(con.execute("SELECT COUNT(*) FROM wallet_entries WHERE kind='commission_refund'").fetchone()[0], 0)

    def test_archived_pet_cannot_make_new_request_but_existing_agreement_survives(self):
        booking = self.request(); quote = self.quote()
        with server.db() as con:
            account = json.loads(con.execute("SELECT account FROM users WHERE id='customer'").fetchone()[0])
            account['pets'][0]['archived'] = True
            con.execute("UPDATE users SET account=? WHERE id='customer'", (json.dumps(account),))
        self.expect_error(404, self.quote)
        self.expect_error(409, lambda: self.request(quote))
        accepted = self.act(booking)
        self.assertEqual(accepted['snapshot']['pets'][0]['name'], 'customer cat')

    def test_home_visit_daily_fixed_price_and_owned_address_snapshot(self):
        data = copy.deepcopy(self.listing)
        data['listings'].append(dict(data['listings'][0], type='homeVisit', capacity=None, location=None))
        self.save(data, revision=2)
        with server.db() as con:
            catalog.review(con, 'abc', 'homeVisit', {'decision':'approve','reason':'TEST','testOnly':True,'_revision':3}, 'admin', 'local')
        with server.db() as con:
            account = json.loads(con.execute("SELECT account FROM users WHERE id='customer'").fetchone()[0])
            account['addresses'] = [{'id':'home','address':'PRIVATE CUSTOMER STREET','lat':41.3,'lon':69.2}]
            con.execute("UPDATE users SET account=? WHERE id='customer'", (json.dumps(account),))
        with self.assertRaises(ValueError): self.quote(listing='abc:homeVisit')
        self.expect_error(404, lambda: self.quote(listing='abc:homeVisit', address='foreign-address'))
        quote = self.quote(listing='abc:homeVisit', address='home', pets=['cat-a','cat-b'])
        self.assertEqual(quote['snapshot']['price']['service_total_minor'],300000000)
        self.assertFalse(quote['snapshot']['visitTerms']['durationAffectsPrice'])
        self.assertIsNone(quote['snapshot']['visitTerms']['fixedVisitCount'])
        self.assertNotIn('PRIVATE CUSTOMER STREET',json.dumps(quote))
        accepted = self.act(self.request(quote))
        self.assertEqual(accepted['snapshot']['address']['address'],'PRIVATE CUSTOMER STREET')
