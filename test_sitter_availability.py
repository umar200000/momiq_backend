import copy
from datetime import datetime, timedelta, timezone
import json
import unittest
from urllib.parse import urlencode

import booking_engine as engine
import catalog
import server
import sitter_availability as availability
import test_booking_engine as fixtures
import test_booking_http as http_fixtures


class AvailabilityTests(unittest.TestCase):
    setUp = fixtures.BookingEngineTests.setUp
    save = fixtures.BookingEngineTests.save
    review = fixtures.BookingEngineTests.review
    quote = fixtures.BookingEngineTests.quote
    request = fixtures.BookingEngineTests.request
    act = fixtures.BookingEngineTests.act
    expect_error = fixtures.BookingEngineTests.expect_error

    def calendar(self, *, dates=None, days=None, start=540, end=1080):
        with server.db() as con:
            con.execute('BEGIN IMMEDIATE')
            before = json.loads(con.execute("SELECT account FROM users WHERE id='abc'").fetchone()[0])
            after = copy.deepcopy(before)
            after['sitterProfile']['closedDates'] = dates or []
            after['sitterProfile']['schedule'] = {'days': days or [True]*7, 'start': start, 'end': end, 'timezone':'Asia/Tashkent'}
            catalog.invalidate_profile(con, 'abc', before, after)
            con.execute("UPDATE users SET account=? WHERE id='abc'", (json.dumps(after),))
            return after

    def test_overnight_endpoints_timezone_and_start_only_blackout(self):
        # Monday 10:00 -> Tuesday 10:00 Tashkent; Tuesday is a closed arrival date.
        start = datetime(2026,11,2,5,tzinfo=timezone.utc)
        end = start+timedelta(days=1)
        account = self.calendar(dates=['2026-11-03'])
        self.assertIsNone(availability.reason(account,start,end))
        self.quote(start=start,end=end)
        self.assertIsNotNone(availability.reason(account,end,end+timedelta(days=1)))
        self.assertIsNone(availability.reason(account,start.replace(hour=4),end.replace(hour=13)))
        self.assertIsNotNone(availability.reason(account,start.replace(hour=3,minute=59),end))
        self.assertIsNotNone(availability.reason(account,start,end.replace(hour=13,microsecond=1)))
        # Off-days in the middle do not block an overnight stay.
        account=self.calendar(days=[True,False,True,True,True,False,False])
        self.assertIsNone(availability.reason(account,start,end+timedelta(days=1)))
        self.assertIsNotNone(availability.reason(account,start,end))
        # Local date is +05, even when the caller supplies UTC the day before.
        account=self.calendar(dates=['2026-11-03'],start=0,end=1439)
        midnight=datetime(2026,11,2,19,tzinfo=timezone.utc)
        self.assertIsNotNone(availability.reason(account,midnight,midnight+timedelta(hours=1)))

    def test_changed_calendar_rechecked_before_request_accept_without_debit(self):
        quote=self.quote()
        booking=self.request(quote)
        self.calendar(dates=[self.start.astimezone(availability.ZONE).date().isoformat()])
        self.expect_error(409,lambda:self.quote())
        self.expect_error(409,lambda:self.act(booking))
        # Exact retry of an already recorded request remains idempotent.
        self.assertEqual(self.request(quote)['id'],booking['id'])
        with server.db() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM wallet_entries WHERE kind='commission'").fetchone()[0],0)
            self.assertEqual(catalog.document(con,'abc')['moderation']['boarding']['status'],'approved')
        self.calendar(start=0,end=1439)
        stale=self.quote(user='other')
        self.calendar(dates=[self.start.astimezone(availability.ZONE).date().isoformat()],start=0,end=1439)
        self.expect_error(409,lambda:self.request(stale,user='other'))

    def test_accepted_obligations_survive_calendar_edits_and_stale_approval_not_revived(self):
        booking=self.act(self.request())
        self.calendar(dates=[self.start.astimezone(availability.ZONE).date().isoformat()])
        one=self.act(booking,'start',now=self.start)
        two=self.act(one,'start',user='customer',now=self.start)
        self.assertEqual(two['status'],'active')
        with server.db() as con:
            con.execute("UPDATE listing_moderation SET approved_hash='stale' WHERE user_id='abc'")
        self.calendar(start=0,end=1439)
        with server.db() as con:
            self.assertEqual(catalog.profiles(con,'local'),[])
            self.assertEqual(con.execute("SELECT approved_hash FROM listing_moderation WHERE user_id='abc'").fetchone()[0],'stale')

    def test_calendar_validation_and_old_client_omission(self):
        account=self.calendar(dates=['2026-11-04','2026-11-03'])
        self.assertEqual(server.validate_account(account)['sitterProfile']['closedDates'],['2026-11-03','2026-11-04'])
        for invalid in [None,{},['2026-02-30'],['2026-1-01'],[True],['2026-11-03']*2,['2026-11-03']*367]:
            data=copy.deepcopy(account);data['sitterProfile']['closedDates']=invalid
            with self.assertRaises(ValueError):server.validate_account(data)
        incoming=copy.deepcopy(account);incoming['sitterProfile'].pop('closedDates')
        after=server.validate_account(incoming)
        availability.preserve_omitted(account,after,incoming)
        self.assertEqual(after['sitterProfile']['closedDates'],account['sitterProfile']['closedDates'])
        incoming['sitterProfile']['closedDates']=[]
        after=server.validate_account(incoming)
        availability.preserve_omitted(account,after,incoming)
        self.assertEqual(after['sitterProfile']['closedDates'],[])


class AvailabilityHttpTests(unittest.TestCase):
    setUp=http_fixtures.BookingHttpTests.setUp
    save=http_fixtures.BookingHttpTests.save
    review=http_fixtures.BookingHttpTests.review
    req=http_fixtures.BookingHttpTests.req
    stop_http=http_fixtures.BookingHttpTests.stop_http

    def test_calendar_cas_discovery_filter_and_old_client_roundtrip(self):
        before=self.req('/api/me',user='abc')['account']
        stale=copy.deepcopy(before)
        start=datetime.fromisoformat(self.payload['startsAt'])
        date=start.astimezone(availability.ZONE).date().isoformat()
        before['sitterProfile']['closedDates']=[date]
        after=self.req('/api/me','PUT',before,user='abc')['account']
        self.req('/api/me','PUT',stale,user='abc',status=409)
        public=self.req('/api/sitters')['sitters']
        self.assertEqual(public[0]['availability']['closedDates'],[date])
        self.assertFalse(public[0]['availabilityKnown'])
        query=urlencode({k:self.payload[k] for k in ('startsAt','endsAt')})
        self.assertEqual(self.req('/api/sitters?'+query)['sitters'],[])
        for query in ['startsAt=bad','startsAt=&endsAt=','startsAt=2026-11-01&endsAt=2026-11-02',query+'&startsAt=duplicate']:
            self.req('/api/sitters?'+query,status=400)
        after['sitterProfile'].pop('closedDates')
        saved=self.req('/api/me','PUT',after,user='abc')['account']
        self.assertEqual(saved['sitterProfile']['closedDates'],[date])
        saved['sitterProfile']['closedDates']=[]
        self.req('/api/me','PUT',saved,user='abc')
        query=urlencode({k:self.payload[k] for k in ('startsAt','endsAt')})
        self.assertEqual(len(self.req('/api/sitters?'+query)['sitters']),1)
