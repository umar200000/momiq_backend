from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import retention_review as review
import server
import test_api


class CalendarTests(unittest.TestCase):
    def test_two_calendar_years_and_exact_boundary(self):
        anchor = '2024-03-01T00:00:00+05:00'
        expiry = datetime.fromisoformat('2026-03-01T00:00:00+05:00')
        self.assertEqual(review.two_years(anchor), expiry)
        self.assertEqual(review.decision([anchor], [], expiry - timedelta(microseconds=1))['state'], 'retained')
        result = review.decision([anchor], [], expiry)
        self.assertEqual(result['state'], 'expired_review')
        self.assertFalse(result['deletionAllowed'])

    def test_leap_day_uses_tashkent_calendar_not_utc_date_or_730_days(self):
        self.assertEqual(review.two_years('2024-02-28T20:00:00Z').isoformat(), '2026-02-28T01:00:00+05:00')
        self.assertEqual(review.two_years('2023-03-01T00:00:00+05:00').isoformat(), '2025-03-01T00:00:00+05:00')

    def test_invalid_missing_naive_future_and_overflow_are_held(self):
        now = datetime(2026, 11, 12, tzinfo=timezone.utc)
        for anchor in (None, '', 'garbage', '2020-01-01', '2020-01-01T10:00:00', '9999-01-01T00:00:00Z', '2027-01-01T00:00:00Z'):
            with self.subTest(anchor=anchor):
                result = review.decision([anchor], [], now)
                self.assertEqual(result['state'], 'held')
                self.assertTrue(result['holds'])
                self.assertFalse(result['deletionAllowed'])
        self.assertEqual(review.decision([], [], now)['state'], 'held')


class DatabaseReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = patch.object(server, 'DATA', Path(self.temp.name))
        patcher.start(); self.addCleanup(patcher.stop)
        server.setup()
        self.now = datetime(2026, 11, 12, tzinfo=timezone.utc)
        self.old = '2020-01-01T00:00:00Z'
        with server.db() as con:
            for user in ('owner', 'sitter'):
                con.execute('INSERT INTO users VALUES(?,?,?,0,?)', (user, '99890000000' + str(len(user)), '{}', self.old))
            con.execute("INSERT INTO booking_quotes VALUES('q','owner','sitter','boarding','{}',?,?,1)", (self.old, self.old))
            con.execute("""INSERT INTO bookings(id,quote_id,customer_id,sitter_id,service,starts_at,ends_at,reply_deadline,status,created,updated)
                VALUES('b','q','owner','sitter','boarding',?,'2020-01-02T00:00:00Z',?,'completed',?,?)""", (self.old, self.old, self.old, self.old))

    def assess(self, category, row):
        with server.db() as con:
            return review.assess(con, category, row, self.now)

    def support(self, status='open', updated=None):
        with server.db() as con:
            con.execute("INSERT INTO support_tickets(id,owner_id,booking_id,subject,topic,status,revision,created,updated) VALUES('s','owner','b','SECRET subject','general',?,1,?,?)",
                        (status, self.old, updated or self.old))

    def dispute(self, status='open', resolved=None):
        with server.db() as con:
            con.execute("INSERT INTO booking_disputes(booking_id,kind,reporter,prior_status,status,revision,created,deadline,resolved_at) VALUES('b','service','owner','active',?,1,?,?,?)",
                        (status, self.old, self.old, resolved))

    def test_payment_holds_for_either_party_active_booking_dispute_support(self):
        row = {'id': '0'*32, 'user_id': 'sitter', 'created': self.old}
        self.assertEqual(self.assess('wallet', row)['state'], 'expired_review')
        with server.db() as con: con.execute("UPDATE bookings SET status='active' WHERE id='b'")
        self.assertIn('active_booking', self.assess('wallet', row)['holds'])
        with server.db() as con: con.execute("UPDATE bookings SET status='completed' WHERE id='b'")
        self.dispute()
        self.assertIn('open_dispute', self.assess('wallet', row)['holds'])
        self.support()
        self.assertIn('open_support', self.assess('wallet', row | {'user_id': 'owner'})['holds'])
        self.assertIn('open_support', self.assess('wallet', row)['holds'])

    def test_resolved_dispute_and_later_appeal_extend_original_evidence(self):
        self.dispute('resolved', '2025-01-01T00:00:00Z')
        self.support('resolved', '2026-02-01T00:00:00Z')
        with server.db() as con:
            row = con.execute('SELECT * FROM booking_disputes').fetchone()
        result = self.assess('disputes', row)
        self.assertEqual(result['state'], 'retained')
        self.assertEqual(result['reviewAt'], '2028-02-01T05:00:00+05:00')
        payment = self.assess('wallet', {'id': '0'*32, 'user_id': 'sitter', 'created': self.old})
        self.assertEqual(payment['reviewAt'], result['reviewAt'])
        with server.db() as con: con.execute("UPDATE support_tickets SET status='open' WHERE id='s'")
        self.assertIn('open_support', self.assess('disputes', row)['holds'])

    def test_support_does_not_expire_while_booking_or_dispute_open(self):
        self.support('resolved')
        with server.db() as con:
            row = con.execute('SELECT * FROM support_tickets').fetchone()
            con.execute("UPDATE bookings SET status='active' WHERE id='b'")
        self.assertIn('active_booking', self.assess('support', row)['holds'])
        self.dispute()
        self.assertIn('open_dispute', self.assess('support', row)['holds'])

    def test_topup_status_final_timestamp_and_correction_history(self):
        row = {'id': 'a'*32, 'user_id': 'owner', 'created': self.old, 'status': 'pending', 'reviewed_at': None}
        self.assertIn('unresolved_topup', self.assess('topups', row)['holds'])
        self.assertIn('invalid_timestamp', self.assess('topups', row | {'status': 'approved'})['holds'])
        final = row | {'status': 'approved', 'reviewed_at': '2025-11-12T00:00:00Z'}
        self.assertEqual(self.assess('topups', final)['state'], 'retained')

    def test_report_open_and_resolved_dates(self):
        row = {'id': 1, 'reporter_id': 'owner', 'created': self.old, 'reviewed_at': self.old, 'status': 'open'}
        self.assertIn('open_report', self.assess('chatReports', row)['holds'])
        self.assertEqual(self.assess('chatReports', row | {'status': 'dismissed'})['state'], 'expired_review')

    def test_later_financial_correction_extends_both_original_and_receipt(self):
        topup, original, corrected = 'a'*32, 'b'*32, 'c'*32
        recent = '2026-01-01T00:00:00Z'
        with server.db() as con:
            con.execute("INSERT INTO wallet_accounts VALUES('owner',90)")
            con.execute("INSERT INTO topup_requests(id,user_id,amount_minor,receipt,receipt_hash,qr_version,terms_version,request_id,status,created,reviewed_at) VALUES(?,'owner',100,'SECRET receipt','TEST hash',1,'TEST terms','TEST request','approved',?,?)", (topup, self.old, self.old))
            for identity, amount, balance, stamp in ((original, 100, 100, self.old), (corrected, -10, 90, recent)):
                con.execute("INSERT INTO wallet_entries VALUES(?,'owner',?,?,'TEST',?,'admin','TEST reason',?)", (identity, amount, balance, identity, stamp))
            con.execute("INSERT INTO wallet_corrections VALUES('TEST correction',?,?,?,10,0,'TEST correction request','admin','TEST reason',?,'owner')", (topup, original, corrected, recent))
            before = list(con.iterdump())
            for category in ('topups', 'wallet'):
                result = review.page(con, category, None, self.now)
                for item in result['items']:
                    self.assertEqual(item['reviewAt'], '2028-01-01T05:00:00+05:00')
                    self.assertEqual(item['state'], 'retained')
                self.assertNotIn('SECRET receipt', json.dumps(result))
            self.assertEqual(list(con.iterdump()), before)
            self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_large_history_stays_bounded_and_held(self):
        with server.db() as con:
            con.execute('CREATE TEMP TABLE test_history(created TEXT)')
            con.executemany('INSERT INTO test_history VALUES(?)', [(self.old,)] * 501)
            anchors, holds = [], []
            review.history_dates(con, 'SELECT created FROM test_history', (), anchors, holds)
        self.assertEqual(len(anchors), 500)
        self.assertEqual(holds, ['history_requires_separate_review'])

    def test_report_reads_never_change_database_or_include_evidence(self):
        self.support('resolved')
        with server.db() as con:
            before = list(con.iterdump())
            for category in review.CATEGORIES:
                result = review.page(con, category, None, self.now)
                self.assertNotIn('SECRET', json.dumps(result))
                self.assertFalse(result['deletionEnabled'])
            self.assertEqual(list(con.iterdump()), before)
            self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(), [])


class RetentionHttpTests(unittest.TestCase):
    setUpClass = classmethod(test_api.ApiTests.setUpClass.__func__)
    tearDownClass = classmethod(test_api.ApiTests.tearDownClass.__func__)
    setUp = test_api.ApiTests.setUp
    req = test_api.ApiTests.req

    def test_admin_only_all_categories_and_readonly_methods(self):
        for endpoint in ('retention-review', 'audit-archive'):
            path = '/api/admin/' + endpoint
            self.req(path, expected=401)
            self.assertEqual(self.req(path, admin=True)['mode'], 'review_only')
            for method in ('POST', 'PUT', 'DELETE'):
                self.req(path, method, {}, admin=True, expected=405)
        for category in review.CATEGORIES:
            self.assertEqual(self.req('/api/admin/retention-review?category='+category, admin=True)['category'], category)
        for role in ('finance', 'moderation', 'support'):
            with server.db() as con: con.execute("UPDATE admin_permissions SET role=? WHERE username='admin'", (role,))
            try:
                self.req('/api/admin/login','POST',{'username':'admin','password':'test-admin-password'},admin=True)
                for endpoint in ('retention-review', 'audit-archive'):
                    self.req('/api/admin/'+endpoint, admin=True, expected=403)
            finally:
                with server.db() as con: con.execute("UPDATE admin_permissions SET role='administrator' WHERE username='admin'")

    def test_strict_parameters_no_delete_switch_or_time_override(self):
        for query in ('category=users', 'category=audit&category=wallet', 'before=0', 'before=-1', 'before=', 'now=2099', 'delete=true', 'category=wallet&before=1', 'before=9999999999999999999'):
            self.req('/api/admin/retention-review?' + query, admin=True, expected=400)
        self.req('/api/admin/audit-archive?category=wallet', admin=True, expected=400)

    def test_archive_pagination_originals_immutable_and_read_audit(self):
        with server.db() as con:
            con.executemany('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)', [('TEST admin','TEST archive','TEST target','2020-01-01T00:00:00Z')] * 55)
        first = self.req('/api/admin/audit-archive', admin=True)
        second = self.req('/api/admin/audit-archive?before='+first['nextCursor'], admin=True)
        self.assertEqual(len(first['items']), 50)
        self.assertFalse({r['id'] for r in first['items']} & {r['id'] for r in second['items']})
        self.assertEqual(first['items'][0]['record']['target'], 'TEST target')
        with server.db() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM audit WHERE action='TEST archive'").fetchone()[0], 55)
            self.assertIsNotNone(con.execute("SELECT 1 FROM audit WHERE action='audit-archive-view'").fetchone())
            for sql in ('DELETE FROM audit', 'UPDATE audit SET actor=actor', 'INSERT OR REPLACE INTO audit SELECT * FROM audit'):
                with self.assertRaises(sqlite3.IntegrityError): con.execute(sql)

    def test_failed_audit_withholds_private_result(self):
        with server.db() as con:
            con.execute("CREATE TRIGGER fail_retention_audit BEFORE INSERT ON audit WHEN NEW.action IN ('audit-archive-view','retention-review') BEGIN SELECT RAISE(ABORT,'TEST unavailable'); END")
        try:
            for endpoint in ('retention-review', 'audit-archive'):
                result = self.req('/api/admin/'+endpoint, admin=True, expected=500)
                self.assertNotIn('items', result)
        finally:
            with server.db() as con: con.execute('DROP TRIGGER fail_retention_audit')


if __name__ == '__main__':
    unittest.main()
