import io
import json
import unittest
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults
from wsgiref.validate import validator
import server
from wsgi import application

class ProductionTests(unittest.TestCase):
    def call(self, path, method='GET', data=None, origin=None):
        env = {}; setup_testing_defaults(env)
        raw = json.dumps(data).encode() if data is not None else b''
        env.update(QUERY_STRING='', PATH_INFO=path, REQUEST_METHOD=method, CONTENT_LENGTH=str(len(raw)), CONTENT_TYPE='application/json', HTTP_HOST='admin.momiq.net')
        env['wsgi.input'] = io.BytesIO(raw)
        if origin: env['HTTP_ORIGIN'] = origin
        response = {}
        def start(status, headers, exc_info=None): response.update(status=int(status.split()[0]), headers=dict(headers))
        output = validator(application)(env, start)
        try: response['body'] = b''.join(output)
        finally:
            if hasattr(output, 'close'): output.close()
        return response

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

if __name__=='__main__': unittest.main()
