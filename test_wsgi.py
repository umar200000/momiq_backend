import io
import json
import unittest
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults
from wsgiref.validate import validator
import server
from wsgi import application

class ProductionTests(unittest.TestCase):
    def test_disconnect_while_sending_rejection_is_counted_once(self):
        from contextlib import redirect_stdout
        from wsgi import WsgiHandler
        env = {}
        setup_testing_defaults(env)
        handler = WsgiHandler(env)
        def disconnect(status,body):
            handler.send_response(status)
            raise BrokenPipeError('private stream data')
        output = io.StringIO()
        with (patch.object(handler,'handle_request',side_effect=server.ApiError(403,'private message')),
              patch.object(handler,'reply',side_effect=disconnect), redirect_stdout(output)):
            handler.dispatch()
        record = json.loads(output.getvalue())
        self.assertEqual((record['status'],record['outcome']),(403,'disconnected'))
        self.assertNotIn('private',output.getvalue())

    def test_locked_database_is_retryable_and_diagnostics_exclude_private_fields(self):
        from contextlib import redirect_stdout
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp, patch.object(server, 'DATA', Path(tmp)), patch.dict(
                'os.environ', MOMIQ_ADMIN_PASSWORD='TEST-operator-private'):
            server.setup()
            original_db = server.db
            def short_timeout():
                con = original_db()
                con.execute('PRAGMA busy_timeout=5')
                return con
            payload = {'username':'admin','password':'TEST-operator-private'}
            output = io.StringIO()
            with redirect_stdout(output), patch.object(server, 'db', short_timeout):
                with original_db() as writer:
                    writer.execute('BEGIN IMMEDIATE')
                    locked = self.call('/api/admin/login?x=private-marker','POST',payload)
                self.assertEqual(locked['status'],503)
                self.assertNotIn('Set-Cookie',locked['headers'])
                self.assertEqual(self.call('/api/admin/login','POST',payload)['status'],200)
                with original_db() as con:
                    con.execute('DROP TABLE attempts')
                self.assertEqual(self.call('/api/admin/login','POST',payload)['status'],500)
            rows = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual([(r['status'],r['outcome']) for r in rows],
                             [(503,'database_busy'),(200,'ok'),(500,'server_error')])
            for row in rows:
                self.assertEqual(set(row),{'event','group','method','status','durationMs','outcome'})
                self.assertEqual((row['method'],row['group']),('POST','admin/login'))
                self.assertGreaterEqual(row['durationMs'],0)
            self.assertNotIn('private-marker',output.getvalue())
            self.assertNotIn('TEST-operator-private',output.getvalue())

    def call(self, path, method='GET', data=None, origin=None, cookie=None, authorization=None):
        env = {}; setup_testing_defaults(env)
        raw = json.dumps(data).encode() if data is not None else b''
        route, _, query = path.partition('?')
        env.update(QUERY_STRING=query, PATH_INFO=route, REQUEST_METHOD=method, CONTENT_LENGTH=str(len(raw)), CONTENT_TYPE='application/json', HTTP_HOST='admin.momiq.net')
        env['wsgi.input'] = io.BytesIO(raw)
        if origin is not None: env['HTTP_ORIGIN'] = origin
        if cookie is not None: env['HTTP_COOKIE'] = cookie
        if authorization is not None: env['HTTP_AUTHORIZATION'] = authorization
        response = {}
        def start(status, headers, exc_info=None): response.update(status=int(status.split()[0]), headers=dict(headers))
        output = validator(application)(env, start)
        try: response['body'] = b''.join(output)
        finally:
            if hasattr(output, 'close'): output.close()
        return response

    def test_request_limits_and_readiness_use_actual_wsgi_target(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        prefix = '/api/health?q='
        with TemporaryDirectory() as root, patch.object(server,'DATA',Path(root)), patch.object(server,'RELEASE_SHA','a'*40):
            self.assertEqual(self.call('/api/health?'+'&'.join(['q=1']*32))['status'],200)
            self.assertEqual(self.call('/api/me?'+'&'.join(['q=1']*33))['status'],400)
            self.assertEqual(self.call(prefix+'x'*(4096-len(prefix)))['status'],200)
            self.assertEqual(self.call(prefix+'x'*(4097-len(prefix)))['status'],414)
            self.assertEqual(self.call('/api/ready')['status'],503)
            self.assertFalse((Path(root)/'momiq.sqlite3').exists())
            server.setup()
            with server.db() as con:
                before=list(con.iterdump())
            status=self.call('/api/ready')
            self.assertEqual(status['status'],200)
            self.assertEqual(json.loads(status['body'])['releaseSha'],'a'*40)
            with server.db() as con:
                self.assertEqual(before,list(con.iterdump()))
                con.execute('DROP TABLE listings')
            self.assertEqual(self.call('/api/ready')['status'],503)

    def test_wsgi_static_admin(self):
        r = self.call('/admin/')
        self.assertEqual(r['status'], 200)
        self.assertIn(b'loginForm', r['body'])

    def test_production_rejects_http_origin(self):
        with patch.object(server, 'PRODUCTION', True):
            self.assertEqual(self.call('/api/admin/login','POST',{},'http://admin.momiq.net')['status'],403)

    def test_production_login_is_closed_without_explicit_test_mode(self):
        # Use an isolated database; the request opens a DB before checking route.
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp, patch.object(server,'DATA',Path(tmp)), patch.object(server,'DEV_LOGIN',False):
            r=self.call('/api/auth/login','POST',{'phone':'998901234567','code':'111111'})
            self.assertEqual(r['status'],503)

    def test_secure_cookie_transport(self):
        from wsgi import WsgiHandler
        env={}; setup_testing_defaults(env)
        with patch.object(server,'PRODUCTION',True):
            h=WsgiHandler(env); h.reply(200,{},'session=example; HttpOnly')
            self.assertIn('; Secure',dict(h.response_headers)['Set-Cookie'])

    def test_production_operator_cookie_csrf_and_logout_with_disposable_database(self):
        from http.cookies import SimpleCookie
        from pathlib import Path
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp, patch.object(server,'DATA',Path(tmp)), patch.object(server,'PRODUCTION',True), patch.dict('os.environ',MOMIQ_ADMIN_PASSWORD='test-operator-secret'):
            server.setup()
            origin='https://admin.momiq.net'
            response=self.call('/api/admin/login','POST',{'username':'admin','password':'test-operator-secret'},origin)
            self.assertEqual(response['status'],200)
            cookie=SimpleCookie(response['headers']['Set-Cookie'])['momiq_admin']
            self.assertTrue(cookie['secure'] and cookie['httponly'])
            self.assertEqual((cookie['samesite'],cookie['path'],cookie['domain']),('Strict','/api/admin',''))
            token='momiq_admin='+cookie.value
            for invalid in ('',origin+'/path',origin+'?extra','null','https://foreign.invalid','http://admin.momiq.net'):
                self.assertEqual(self.call('/api/admin/logout','POST',{},invalid,token)['status'],403)
            self.assertEqual(self.call('/api/admin/users',origin=origin,cookie=token)['status'],200)
            closed=self.call('/api/admin/logout','POST',{},origin,token)
            self.assertEqual(closed['status'],200)
            self.assertEqual(SimpleCookie(closed['headers']['Set-Cookie'])['momiq_admin']['max-age'],'0')
            self.assertEqual(self.call('/api/admin/users',origin=origin,cookie=token)['status'],401)

    def test_password_changed_during_operator_login_cannot_issue_a_session(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp, patch.object(server, 'DATA', Path(tmp)), patch.dict(
                'os.environ', MOMIQ_ADMIN_PASSWORD='TEST-previous-password'):
            server.setup()
            original = server.password_hash
            def rotate_while_checking(password, salt):
                with server.db() as writer:
                    writer.execute("UPDATE admins SET hash=? WHERE username='admin'",
                                   (original('TEST-updated-password', salt),))
                return original(password, salt)

            with patch.object(server, 'password_hash', side_effect=rotate_while_checking):
                response = self.call('/api/admin/login', 'POST',
                                     {'username':'admin', 'password':'TEST-previous-password'})
            self.assertEqual(response['status'], 401)
            self.assertNotIn('Set-Cookie', response['headers'])
            with server.db() as con:
                self.assertEqual(con.execute("SELECT count(*) FROM sessions").fetchone()[0], 0)
            response = self.call('/api/admin/login', 'POST',
                                 {'username':'admin', 'password':'TEST-updated-password'})
            self.assertEqual(response['status'], 200)
            cookie = response['headers']['Set-Cookie'].split(';')[0]
            with server.db() as con:
                con.execute("DELETE FROM admins WHERE username='admin'")
            self.assertEqual(self.call('/api/admin/users', cookie=cookie)['status'], 401)

    def test_parallel_login_attempts_share_one_quota(self):
        from concurrent.futures import ThreadPoolExecutor
        from pathlib import Path
        from tempfile import TemporaryDirectory
        import threading
        with TemporaryDirectory() as tmp, patch.object(server,'DATA',Path(tmp)):
            server.setup()
            barrier=threading.Barrier(20)
            def attempt(_):
                with server.db() as con:
                    barrier.wait(timeout=10)
                    try:
                        server.Handler.throttle(None,con,'test-quota')
                    except server.ApiError as error:
                        return error.status
                    return 200
            with ThreadPoolExecutor(20) as pool:
                codes=list(pool.map(attempt,range(20)))
            self.assertCountEqual(codes,[200]*15+[429]*5)

    def test_ambiguous_credentials_cannot_read_or_revoke_a_valid_session(self):
        import hashlib
        import time
        from tempfile import TemporaryDirectory
        from pathlib import Path
        with TemporaryDirectory() as tmp, patch.object(server,'DATA',Path(tmp)):
            server.setup()
            with server.db() as con:
                con.execute('INSERT INTO users VALUES(?,?,?,0,?)',('client','998000000000',json.dumps(server.default_account()),server.now()))
                for token,owner,role in [('test-client','client','client'),('test-admin','admin','admin')]:
                    con.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),owner,role,time.time()+60))
            for cookie in ('momiq_admin=invalid; momiq_admin=test-admin','momiq_admin=test-admin; momiq_admin=test-admin'):
                self.assertEqual(self.call('/api/admin/users',cookie=cookie)['status'],401)
                self.assertEqual(self.call('/api/admin/logout','POST',{},cookie=cookie)['status'],401)
            self.assertEqual(self.call('/api/admin/users',cookie='other=ok; momiq_admin=test-admin')['status'],200)
            for auth in ('test-client','Bearer invalid, Bearer test-client','Bearer test-admin'):
                self.assertEqual(self.call('/api/me',authorization=auth)['status'],401)
                self.assertEqual(self.call('/api/auth/logout','POST',{},authorization=auth)['status'],401)
            self.assertEqual(self.call('/api/me',authorization='bearer test-client')['status'],200)
            self.assertEqual(self.call('/api/auth/logout','POST',{},authorization='bearer test-client')['status'],200)
            self.assertEqual(self.call('/api/me',authorization='Bearer test-client')['status'],401)

if __name__=='__main__': unittest.main()
