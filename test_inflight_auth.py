from concurrent.futures import ThreadPoolExecutor
import base64
import hashlib
import json
import secrets
import sqlite3
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener

import server
import test_admin_bookings as fixtures
from test_media import fixture_image


class InflightAuthorizationTests(unittest.TestCase):
    setUp = fixtures.AdminBookingTests.setUp
    save = fixtures.AdminBookingTests.save
    review = fixtures.AdminBookingTests.review
    stop_http = fixtures.AdminBookingTests.stop_http
    req = fixtures.AdminBookingTests.req

    def send(self, path, method, body=None, *, admin=False, client='customer'):
        headers = {'Content-Type': 'application/json'}
        headers.update({'Cookie': 'momiq_admin=' + self.admin_token} if admin else
                       {'Authorization': 'Bearer ' + self.tokens[client]})
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

    def test_oversized_account_actions_preserve_sessions_and_profile(self):
        initial = self.send('/api/me','GET')[1]
        for path in ('/api/me/role','/api/me/pets/archive','/api/auth/logout','/api/auth/logout-all','/api/admin/logout'):
            admin = path == '/api/admin/logout'
            status, response = self.send(path,'POST',{'padding':'x' * 16384},admin=admin)
            self.assertEqual(status, 413, path)
            self.assertEqual(set(response), {'error'})
        self.assertEqual(self.send('/api/me','GET'), (200,initial))
        self.assertEqual(self.send('/api/admin/me','GET',admin=True)[0], 200)

    def test_slow_json_reader_does_not_hold_catalog_or_account_snapshots(self):
        with server.db() as setup:
            self.assertEqual(setup.execute('PRAGMA journal_mode=DELETE').fetchone()[0], 'delete')
        original_reply = server.Handler.reply
        locked = []
        def probe(handler,status,body,cookie=None):
            with server.db() as writer:
                writer.execute('PRAGMA busy_timeout=0')
                writer.execute("INSERT OR REPLACE INTO runtime_metadata VALUES('test_reader',?)",(handler.path,))
                try:
                    writer.commit()
                except sqlite3.OperationalError as error:
                    locked.append((handler.path,str(error)))
                    writer.rollback()
            original_reply(handler,status,body,cookie)

        with patch.object(server.Handler,'reply',probe):
            for path in ('/api/sitters','/api/sitters?favorites=1','/api/notifications',
                         '/api/me/dashboard','/api/me/profile-export','/api/me/listings'):
                self.assertEqual(self.send(path,'GET',client='abc')[0],200)
        self.assertEqual(locked,[])

    def test_dashboard_uses_role_from_same_snapshot_as_private_data(self):
        original = server.ClosingConnection.execute
        def lose_role(connection,sql,parameters=()):
            if sql=='BEGIN' and connection.request_authorizer:
                with server.db() as writer:
                    writer.execute("DELETE FROM user_roles WHERE user_id='abc' AND role='sitter'")
            return original(connection,sql,parameters)
        with patch.object(server.ClosingConnection,'execute',lose_role):
            status,body = self.send('/api/me/dashboard','GET',client='abc')
        self.assertEqual(status,403)
        self.assertEqual(set(body),{'error'})

    def test_revoked_session_cannot_read_account_or_message_history(self):
        original = server.Handler.auth
        def revoke_after_first_check(handler, con, role='client', *, bind=True):
            principal = original(handler, con, role, bind=bind)
            if bind:
                with server.db() as writer:
                    writer.execute('DELETE FROM sessions WHERE user_id=?', (principal,))
            return principal

        for path in ('/api/me', '/api/messages', '/api/admin/me'):
            with self.subTest(path=path), patch.object(server.Handler, 'auth', revoke_after_first_check):
                admin = path == '/api/admin/me'
                if not admin:
                    with server.db() as writer:
                        writer.execute('INSERT OR REPLACE INTO sessions VALUES(?,?,?,?)',
                                       (hashlib.sha256(self.tokens['customer'].encode()).hexdigest(),
                                        'customer', 'client', time.time() + 3600))
                status, body = self.send(path, 'GET', admin=admin)
                self.assertEqual(status, 401)
                self.assertEqual(set(body), {'error'})

    def test_profile_write_receipt_describes_its_own_revision(self):
        status, result = self.send('/api/me', 'GET')
        self.assertEqual(status, 200)
        account = result['account']
        account.update(pets=[])
        account['profile']['first'] = 'First writer'
        original_commit = server.ClosingConnection.commit
        def write_after_commit(connection):
            original_commit(connection)
            if connection.request_authorizer:
                with server.db() as other:
                    other.execute("UPDATE users SET account=json_set(account,'$.profile.first','Second writer') WHERE id='customer'")
                    other.execute("UPDATE account_revisions SET revision=revision+1 WHERE user_id='customer'")

        with patch.object(server.ClosingConnection, 'commit', write_after_commit):
            status, receipt = self.send('/api/me', 'PUT', account)
        self.assertEqual(status, 200)
        self.assertEqual(receipt['account']['_revision'], account['_revision'] + 1)
        self.assertEqual(receipt['account']['profile']['first'], 'First writer')
        current = self.send('/api/me', 'GET')[1]['account']
        self.assertEqual(current['_revision'], account['_revision'] + 2)
        self.assertEqual(current['profile']['first'], 'Second writer')

    def pending_topup(self, identity):
        receipt = fixture_image('purple')
        digest = hashlib.sha256(base64.b64decode(receipt)).hexdigest()
        with server.db() as con:
            con.execute(
                'INSERT INTO topup_requests(id,user_id,amount_minor,receipt,receipt_hash,qr_version,terms_version,request_id,status,created) '
                'VALUES(?,?,?,?,?,?,?,?,?,?)',
                (identity,'abc',10000,receipt,digest,1,server.wallet.TERMS_VERSION,'TEST '+identity,'pending',server.now()),
            )
            server.wallet.topup_history.record(con,identity,'submitted','abc')

    def test_topup_summaries_do_not_read_receipt_and_revoked_owner_cannot_reopen_one(self):
        identity = 'd' * 32
        self.pending_topup(identity)
        original_db = server.db
        def metadata_only():
            con = original_db()
            def authorize(action, table, column, *_):
                if action == sqlite3.SQLITE_READ and (table, column) == ('topup_requests','receipt'):
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            con.set_authorizer(authorize)
            return con

        path = '/api/wallet/topups/' + identity
        with patch.object(server, 'db', metadata_only):
            for route in (path, '/api/wallet/topups', '/api/admin/topups'):
                with self.subTest(route=route):
                    status, response = self.send(route,'GET',admin=route.startswith('/api/admin'),client='abc')
                    self.assertEqual(status, 200)
                    topup = response['topup'] if route == path else response['topups'][0]
                    self.assertEqual(topup['id'], identity)
                    self.assertEqual(topup['amountMinor'], 10000)
                    self.assertNotIn('receipt', topup)

        original_auth = server.Handler.auth
        def revoke(handler, connection, role='client', *, bind=True):
            user = original_auth(handler, connection, role, bind=bind)
            if bind:
                with original_db() as other:
                    other.execute('DELETE FROM sessions WHERE user_id=?',(user,))
            return user

        with patch.object(server.Handler,'auth',revoke):
            status, response = self.send(path,'GET',client='abc')
        self.assertEqual(status, 401)
        self.assertEqual(set(response), {'error'})

    def test_review_acknowledgement_precedes_a_concurrent_receipt_resubmission(self):
        identity = 'e' * 32
        self.pending_topup(identity)
        amended = {'revision':1,'qrVersion':1,'amountMinor':10000,'receipt':fixture_image('yellow'),
                   'acceptNonRefundable':True,'termsVersion':server.wallet.TERMS_VERSION,
                   'requestId':'TEST resubmit','payerReference':'TEST resubmitted transfer'}
        responses = []
        original = server.ClosingConnection.commit
        def resubmit_after_review(connection):
            original(connection)
            if connection.request_authorizer and not responses:
                responses.append(None)
                responses[0] = self.send('/api/wallet/topups/'+identity+'/amend','POST',amended,client='abc')

        with patch.object(server.ClosingConnection,'commit',resubmit_after_review):
            status, response = self.send('/api/admin/topups/'+identity+'/review','POST',
                                         {'revision':0,'decision':'request_info','reason':'TEST check incoming'},admin=True)
        self.assertEqual(responses[0][0], 200)
        self.assertEqual(status, 200)
        self.assertEqual((response['topup']['status'], response['topup']['revision']), ('needs_info',1))
        self.assertEqual((responses[0][1]['topup']['status'], responses[0][1]['topup']['revision']), ('pending',2))

    def test_archive_and_exact_retry_return_the_snapshot_before_commit(self):
        rev = self.send('/api/me','GET')[1]['account']['_revision']
        body = {'petId':'owned','archived':True,'_revision':rev}
        original = server.account_snapshot
        snapshots = []
        def record(connection, user_id):
            snapshots.append(connection.in_transaction)
            return original(connection, user_id)

        with patch.object(server, 'account_snapshot', record):
            for _ in range(2):
                status, response = self.send('/api/me/pets/archive','POST',body)
                self.assertEqual(status, 200)
                self.assertEqual(response['account']['_revision'], rev+1)
                self.assertTrue(next(p for p in response['account']['pets'] if p['id']=='owned')['archived'])
        self.assertEqual(snapshots, [True,True])

    def test_admin_reply_checks_recipient_after_reading_body(self):
        with server.db() as con:
            con.execute("INSERT INTO sitters(id,profile) VALUES('test-legacy','{}')")
        original = server.Handler.body
        def block_recipient(handler):
            data = original(handler)
            with server.db() as other:
                other.execute("UPDATE users SET blocked=1 WHERE id='abc'")
            return data

        with patch.object(server.Handler, 'body', block_recipient):
            status, body = self.send('/api/admin/users/abc/messages', 'POST',
                                     {'sitter':'test-legacy', 'text':'TEST reply', 'requestId':'TEST blocked'}, admin=True)
        self.assertEqual(status, 409)
        self.assertEqual(set(body), {'error'})
        with server.db() as con:
            self.assertFalse(con.execute("SELECT 1 FROM messages WHERE request_id='TEST blocked'").fetchone())
            self.assertFalse(con.execute("SELECT 1 FROM audit WHERE action='reply'").fetchone())

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
