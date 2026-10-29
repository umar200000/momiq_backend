from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import secrets
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener

import server
import test_admin_bookings as fixtures


class InflightAuthorizationTests(unittest.TestCase):
    setUp = fixtures.AdminBookingTests.setUp
    save = fixtures.AdminBookingTests.save
    review = fixtures.AdminBookingTests.review
    stop_http = fixtures.AdminBookingTests.stop_http
    req = fixtures.AdminBookingTests.req

    def send(self, path, method, body=None, *, admin=False):
        headers = {'Content-Type': 'application/json'}
        headers.update({'Cookie': 'momiq_admin=' + self.admin_token} if admin else
                       {'Authorization': 'Bearer ' + self.tokens['customer']})
        request = Request(self.base + path, method=method, headers=headers,
                          data=json.dumps(body).encode() if body is not None else None)
        try: response = build_opener(ProxyHandler({})).open(request, timeout=10)
        except HTTPError as error: response = error
        with response: return response.status, json.load(response)

    def test_revoked_or_blocked_client_cannot_finish_slow_profile_validation(self):
        original = server.validate_account
        for change, expected in [('logout', 401), ('expiry', 401), ('block', 403)]:
            with self.subTest(change=change):
                with server.db() as con:
                    con.execute("UPDATE users SET blocked=0 WHERE id='customer'")
                    con.execute('INSERT OR REPLACE INTO sessions VALUES(?,?,?,?)',
                                (hashlib.sha256(self.tokens['customer'].encode()).hexdigest(),
                                 'customer', 'client', time.time() + 3600))
                    before = con.execute("SELECT account FROM users WHERE id='customer'").fetchone()[0]
                    revision_row = con.execute("SELECT revision FROM account_revisions WHERE user_id='customer'").fetchone()
                    revision = revision_row[0] if revision_row else 0
                body = json.loads(before); body.update(_revision=revision, pets=[])
                body['profile']['first'] = 'Must not be saved'
                entered, release = threading.Event(), threading.Event()
                def slow(value):
                    entered.set()
                    if not release.wait(5): raise RuntimeError('TEST timeout')
                    return original(value)
                with patch.object(server, 'validate_account', slow), ThreadPoolExecutor(1) as pool:
                    pending = pool.submit(self.send, '/api/me', 'PUT', body)
                    try:
                        self.assertTrue(entered.wait(5))
                        with server.db() as con:
                            if change == 'logout': con.execute("DELETE FROM sessions WHERE user_id='customer'")
                            elif change == 'expiry': con.execute("UPDATE sessions SET expires=0 WHERE user_id='customer'")
                            else: con.execute("UPDATE users SET blocked=1 WHERE id='customer'")
                    finally: release.set()
                    self.assertEqual(pending.result()[0], expected)
                with server.db() as con:
                    self.assertEqual(con.execute("SELECT account FROM users WHERE id='customer'").fetchone()[0], before)
                    after = con.execute("SELECT revision FROM account_revisions WHERE user_id='customer'").fetchone()
                    self.assertEqual(tuple(after) if after else None, tuple(revision_row) if revision_row else None)

    def test_operator_revocation_cancels_pending_legacy_redaction_without_audit(self):
        identity = 'a' * 32
        with server.db() as con:
            con.execute('INSERT INTO messages(id,user_id,sitter,mine,text,time) VALUES(?,?,?,?,?,?)',
                        (identity, 'customer', 'TEST sitter', 1, 'Private evidence stays', server.now()))
        original = server.Handler.body
        for change in ('disable', 'role', 'password', 'expiry'):
            with self.subTest(change=change):
                self.admin_token = secrets.token_hex(32)
                with server.db() as con:
                    con.execute("UPDATE admin_permissions SET role='administrator',enabled=1 WHERE username='TEST operator'")
                    con.execute('INSERT INTO sessions VALUES(?,?,?,?)',
                                (hashlib.sha256(self.admin_token.encode()).hexdigest(), 'TEST operator', 'admin', time.time() + 3600))
                entered, release = threading.Event(), threading.Event()
                def slow(handler):
                    entered.set()
                    if not release.wait(5): raise RuntimeError('TEST timeout')
                    return original(handler)
                with patch.object(server.Handler, 'body', slow), ThreadPoolExecutor(1) as pool:
                    pending = pool.submit(self.send, '/api/admin/messages/' + identity, 'DELETE',
                                          {'reason': 'TEST redaction'}, admin=True)
                    try:
                        self.assertTrue(entered.wait(5))
                        with server.db() as con:
                            if change == 'disable': con.execute("UPDATE admin_permissions SET enabled=0 WHERE username='TEST operator'")
                            elif change == 'role': con.execute("UPDATE admin_permissions SET role='support' WHERE username='TEST operator'")
                            elif change == 'password': con.execute("UPDATE admins SET hash='changed TEST hash' WHERE username='TEST operator'")
                            else: con.execute("UPDATE sessions SET expires=0 WHERE user_id='TEST operator'")
                    finally: release.set()
                    self.assertEqual(pending.result()[0], 401)
                with server.db() as con:
                    self.assertEqual(tuple(con.execute('SELECT text,deleted FROM messages WHERE id=?', (identity,)).fetchone()), ('Private evidence stays', 0))
                    self.assertFalse(con.execute("SELECT 1 FROM audit WHERE action='delete-message'").fetchone())

    def test_revalidation_happens_after_waiting_for_the_writer_lock(self):
        entered = threading.Event(); original = server.ClosingConnection.execute
        def observe(connection, sql, parameters=()):
            if sql == 'BEGIN IMMEDIATE' and connection.request_authorizer:
                entered.set()
            return original(connection, sql, parameters)
        with server.db() as writer, patch.object(server.ClosingConnection, 'execute', observe), ThreadPoolExecutor(1) as pool:
            writer.execute('BEGIN IMMEDIATE')
            writer.execute("DELETE FROM sessions WHERE user_id='customer'")
            pending = pool.submit(self.send, '/api/me/role', 'POST', {'role': 'sitter'})
            try: self.assertTrue(entered.wait(5))
            finally: writer.commit()
            self.assertEqual(pending.result()[0], 401)
        with server.db() as con:
            self.assertFalse(con.execute("SELECT 1 FROM user_roles WHERE user_id='customer' AND role='sitter'").fetchone())
            self.assertFalse(con.execute("SELECT 1 FROM audit WHERE actor='customer' AND action='role-enroll'").fetchone())

    def test_revoked_admin_read_transaction_returns_no_private_index(self):
        entered, release = threading.Event(), threading.Event()
        original = server.Handler.auth
        def slow(handler, con, role='client', *, bind=True):
            result = original(handler, con, role, bind=bind)
            if bind:
                entered.set()
                if not release.wait(5): raise RuntimeError('TEST timeout')
            return result
        with patch.object(server.Handler, 'auth', slow), ThreadPoolExecutor(1) as pool:
            pending = pool.submit(self.send, '/api/admin/users', 'GET', admin=True)
            try:
                self.assertTrue(entered.wait(5))
                with server.db() as con: con.execute("DELETE FROM sessions WHERE user_id='TEST operator'")
            finally: release.set()
            status, body = pending.result()
            self.assertEqual(status, 401); self.assertEqual(set(body), {'error'})

    def test_guard_failure_rolls_back_and_never_leaks_to_another_connection(self):
        with server.db() as con:
            def reject(_): raise server.ApiError(401, 'TEST revoked')
            con.request_authorizer = reject
            for operation in (lambda: con.execute('BEGIN IMMEDIATE'),
                              lambda: con.execute("UPDATE users SET blocked=1 WHERE id='customer'"),
                              lambda: con.executemany('UPDATE users SET blocked=1 WHERE id=?', [('customer',)])):
                with self.assertRaises(server.ApiError): operation()
                self.assertFalse(con.in_transaction)
            with self.assertRaises(RuntimeError): con.executescript('SELECT 1;')
        with server.db() as fresh:
            self.assertIsNone(fresh.request_authorizer)
            self.assertEqual(fresh.execute("SELECT blocked FROM users WHERE id='customer'").fetchone()[0], 0)

    def test_revoked_finance_approval_cannot_credit_balance_or_publish_notice(self):
        identity = 'b' * 32
        self.admin_token = secrets.token_hex(32)
        with server.db() as con:
            con.execute("UPDATE admin_permissions SET role='finance' WHERE username='TEST operator'")
            con.execute('INSERT INTO sessions VALUES(?,?,?,?)',
                        (hashlib.sha256(self.admin_token.encode()).hexdigest(), 'TEST operator', 'admin', time.time()+3600))
            con.execute('INSERT INTO topup_requests(id,user_id,amount_minor,receipt,receipt_hash,qr_version,terms_version,request_id,status,created) VALUES(?,?,?,?,?,?,?,?,?,?)',
                        (identity, 'abc', 10000, 'TEST evidence', 'TEST hash', 1, 'TEST terms', 'TEST request', 'pending', server.now()))
            balance = con.execute("SELECT balance_minor FROM wallet_accounts WHERE user_id='abc'").fetchone()[0]
            entries = con.execute('SELECT count(*) FROM wallet_entries').fetchone()[0]
        entered, release = threading.Event(), threading.Event(); original = server.Handler.body
        def slow(handler):
            entered.set()
            if not release.wait(5): raise RuntimeError('TEST timeout')
            return original(handler)
        body = {'decision': 'approve', 'reason': 'TEST incoming verified', 'transferReference': 'TEST-XOLIS',
                'fundsVerified': True, 'receivedAmountMinor': 10000, 'revision': 0}
        with patch.object(server.Handler, 'body', slow), ThreadPoolExecutor(1) as pool:
            pending = pool.submit(self.send, '/api/admin/topups/'+identity+'/review', 'POST', body, admin=True)
            try:
                self.assertTrue(entered.wait(5))
                with server.db() as con: con.execute("UPDATE admin_permissions SET enabled=0 WHERE username='TEST operator'")
            finally: release.set()
            self.assertEqual(pending.result()[0], 401)
        with server.db() as con:
            self.assertEqual(con.execute("SELECT balance_minor FROM wallet_accounts WHERE user_id='abc'").fetchone()[0], balance)
            self.assertEqual(con.execute('SELECT count(*) FROM wallet_entries').fetchone()[0], entries)
            self.assertEqual(tuple(con.execute('SELECT status,revision FROM topup_requests WHERE id=?', (identity,)).fetchone()), ('pending', 0))
            self.assertFalse(con.execute("SELECT 1 FROM audit WHERE action='topup-approve'").fetchone())
            self.assertFalse(con.execute("SELECT 1 FROM notifications WHERE source_key LIKE 'topup-review:%'").fetchone())
