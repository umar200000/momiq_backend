from contextlib import ExitStack
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import deploy_smoke
import server


class DeploySmokeTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        tmp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(patch.object(server, 'DATA', Path(tmp)))
        self.stack.enter_context(patch.object(server, 'ENVIRONMENT', 'test'))
        self.stack.enter_context(patch.object(server, 'RELEASE_SHA', 'a' * 40))
        server.setup()
        self.responses = {}
        self.boundaries = {}
        self.requests = []
        owner = self

        class Handler(server.Handler):
            def log_message(self, *args): pass
            def log_request(self, *args): pass
            def handle_request(self):
                owner.requests.append((self.command, self.path))
                if self.path in owner.boundaries.get(self.server.server_port, set()):
                    self.send_response(404); self.end_headers(); return
                override = owner.responses.get(self.path)
                if override:
                    status, body, headers = override
                    self.send_response(status)
                    for key, value in headers.items(): self.send_header(key, value)
                    self.end_headers()
                    self.wfile.write(body)
                    return
                super().handle_request()

        self.http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.url = 'http://127.0.0.1:' + str(self.http.server_port)

    def stop(self):
        self.http.shutdown(); self.http.server_close(); self.thread.join()

    def check(self, **kwargs):
        return deploy_smoke.check(self.url, self.url, 'a' * 40, 'test', **kwargs)

    def test_real_read_only_workload_ignores_proxy_and_preserves_every_table(self):
        with server.db() as con: before = '\n'.join(con.iterdump())
        with patch.dict('os.environ', {'HTTP_PROXY': 'http://127.0.0.1:1', 'http_proxy': 'http://127.0.0.1:1',
                                      'NO_PROXY': '', 'no_proxy': ''}):
            result = self.check(admin_dir=server.ADMIN)
        self.assertTrue(result['ok']); self.assertTrue(result['adminBytesVerified'])
        self.assertEqual(len(result['checks']), 26)
        self.assertEqual(set(method for method, _ in self.requests), {'GET'})
        with server.db() as con: self.assertEqual('\n'.join(con.iterdump()), before)
        text = json.dumps(result)
        for secret in ('password', 'Bearer', 'momiq_admin=', str(server.DATA), self.url):
            self.assertNotIn(secret, text)

    def test_wrong_worker_or_environment_and_hosted_test_login_fail(self):
        with patch.object(server, 'RELEASE_SHA', 'b' * 40):
            with self.assertRaisesRegex(deploy_smoke.SmokeFailure, 'wrong release'):
                self.check()
        with self.assertRaises(deploy_smoke.SmokeFailure):
            deploy_smoke.check(self.url, self.url, 'a' * 40, 'production')
        with server.db() as con:
            con.execute("UPDATE runtime_metadata SET value='staging' WHERE key='environment'")
        with patch.object(server, 'ENVIRONMENT', 'staging'), patch.object(server, 'DEV_LOGIN', True):
            with self.assertRaisesRegex(deploy_smoke.SmokeFailure, 'test login'):
                deploy_smoke.check(self.url, self.url, 'a' * 40, 'staging')

    def test_release_smoke_refuses_old_schema_or_missing_mobile_features(self):
        headers={'Content-Type':'application/json','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}
        identity={'ok':True,'mode':'test','releaseSha':'a'*40}
        self.responses['/api/ready']=(200,json.dumps({**identity,'schemaVersion':1}).encode(),headers)
        with self.assertRaisesRegex(deploy_smoke.SmokeFailure,'schema version'):self.check()
        self.responses.clear()
        self.responses['/api/health']=(200,json.dumps({**identity,'mobileFeatures':[]}).encode(),headers)
        with self.assertRaisesRegex(deploy_smoke.SmokeFailure,'capabilities'):self.check()
        self.responses.clear()
        with server.db() as con:con.execute("UPDATE runtime_metadata SET value='production' WHERE key='environment'")
        with patch.object(server,'ENVIRONMENT','production'),patch.object(server,'DEV_LOGIN',False):
            with self.assertRaisesRegex(deploy_smoke.SmokeFailure,'mobile login'):
                deploy_smoke.check(self.url,self.url,'a'*40,'production',mobile_release=True)

    def test_redirect_never_follows_and_protected_success_is_failure(self):
        self.responses['/api/health'] = (302, b'', {'Location': self.url + '/redirect-target'})
        with self.assertRaises(deploy_smoke.SmokeFailure): self.check()
        self.assertEqual(self.requests, [('GET', '/api/health')])
        self.responses.clear(); self.requests.clear()
        self.responses['/api/me'] = (200, b'{"private":"must not print"}', {})
        with self.assertRaisesRegex(deploy_smoke.SmokeFailure, 'unexpected HTTP status 200'):
            self.check()

    def test_stale_admin_bytes_bad_json_and_cache_policy_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'index.html').write_text('old release', encoding='utf-8')
            with self.assertRaisesRegex(deploy_smoke.SmokeFailure, 'asset mismatch'):
                self.check(admin_dir=Path(tmp))
        headers = {'Content-Type': 'application/json', 'Cache-Control': 'no-store',
                   'X-Content-Type-Options': 'nosniff'}
        self.responses['/api/health'] = (200, b'invalid JSON', headers)
        with self.assertRaisesRegex(deploy_smoke.SmokeFailure, 'invalid JSON'): self.check()
        self.responses['/api/health'] = (200, b'{}', {**headers, 'Cache-Control': 'public'})
        with self.assertRaisesRegex(deploy_smoke.SmokeFailure, 'cached'): self.check()
        self.responses['/api/health'] = (200, b'0123456789', headers)
        with patch.object(deploy_smoke, 'MAX_RESPONSE', 8):
            with self.assertRaisesRegex(deploy_smoke.SmokeFailure, 'limit exceeded'): self.check()

    def test_invalid_urls_and_revision_never_send_a_request(self):
        for url in ('http://example.com', 'https://user:pass@example.com', 'https://example.com/path',
                    'https://example.com?token=secret', 'https://example.com/#fragment',
                    'file:///tmp/file', 'https://example.com:bad', 'https://exam ple.com'):
            with self.assertRaises(ValueError):
                deploy_smoke.check(url, self.url, 'a' * 40, 'test')
        with self.assertRaises(ValueError):
            deploy_smoke.check(self.url, self.url, 'main', 'test')
        self.assertEqual(self.requests, [])

    def test_separate_origins_enforce_both_proxy_boundaries(self):
        admin = ThreadingHTTPServer(('127.0.0.1', 0), self.http.RequestHandlerClass)
        thread = threading.Thread(target=admin.serve_forever, daemon=True); thread.start()
        try:
            self.boundaries[self.http.server_port] = {'/api/admin/users'}
            self.boundaries[admin.server_port] = {'/api/me'}
            admin_url = 'http://127.0.0.1:' + str(admin.server_port)
            result = deploy_smoke.check(self.url, admin_url, 'a' * 40, 'test', server.ADMIN)
            self.assertEqual(len(result['checks']), 28)
            self.boundaries[admin.server_port].clear()
            with self.assertRaisesRegex(deploy_smoke.SmokeFailure, 'admin-client-boundary'):
                deploy_smoke.check(self.url, admin_url, 'a' * 40, 'test')
        finally:
            admin.shutdown(); admin.server_close(); thread.join()
