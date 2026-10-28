from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import json
import runpy
import unittest
import server
from request_logging import access_record


class RequestLoggingTests(unittest.TestCase):
    def test_query_path_identity_and_header_like_injection_are_never_logged(self):
        for path in ['/api/sitters?lat=41.123456&lng=69.654321',
                     '/api/admin/users?q=998901234567',
                     '/api/bookings/PRIVATE-ID/videos?token=SECRET',
                     '/api/SECRET/PRIVATE', '/PRIVATE?address=HOME',
                     'https://SECRET.invalid/api/me', '/admin/SECRET.js']:
            value=access_record('GET',path,200)
            self.assertNotIn('SECRET',value);self.assertNotIn('PRIVATE',value)
            self.assertNotIn('41.123456',value);self.assertNotIn('998901234567',value)
            self.assertEqual(json.loads(value)['status'],200)
        self.assertEqual(json.loads(access_record('SECRET\nmethod','/api/me','SECRET'))['method'],'OTHER')

    def test_native_handler_diagnostics_do_not_interpolate_sensitive_values(self):
        handler=server.Handler.__new__(server.Handler)
        handler.path='/api/admin/users/PRIVATE-ID?q=998901234567';handler.command='GET'
        stream=StringIO()
        with redirect_stdout(stream):
            handler.log_request(403)
            handler.log_message('Bad request %r','PRIVATE TOKEN')
        text=stream.getvalue()
        self.assertNotIn('PRIVATE',text);self.assertNotIn('998901234567',text)
        self.assertEqual(json.loads(text.splitlines()[0])['group'],'admin/users')

    def test_hosted_access_formats_contain_only_operational_fields(self):
        config=runpy.run_path('gunicorn.conf.py')
        line=config['access_log_format'] % {'s':403,'b':10,'L':'0.010','r':'SECRET','h':'PRIVATE'}
        self.assertEqual(line,'403 10 0.010')
        nginx=Path('deploy/nginx.conf').read_text()
        format_line=next(s for s in nginx.splitlines() if s.startswith('log_format'))
        self.assertNotIn('$request;',format_line);self.assertNotIn('$request_uri',format_line)
        self.assertEqual(nginx.count('access_log /var/log/nginx/momiq-access.log momiq_private;'),3)


if __name__=='__main__':unittest.main()
