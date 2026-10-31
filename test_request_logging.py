from contextlib import redirect_stdout, closing
from io import StringIO, BytesIO
from pathlib import Path
import json
import runpy
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults
import server
from request_logging import access_record
from wsgi import WsgiHandler


class RequestLoggingTests(unittest.TestCase):
    def handler(self, hosted):
        if hosted:
            env={};setup_testing_defaults(env)
            env.update(PATH_INFO='/api/bookings/PRIVATE-ID',QUERY_STRING='token=SECRET',HTTP_AUTHORIZATION='Bearer SECRET',HTTP_COOKIE='PRIVATE cookie')
            return WsgiHandler(env)
        class Local(server.Handler):
            def send_response(self, code, message=None): self.log_request(code)
            def send_header(self, *_): pass
            def end_headers(self): pass
        handler=Local.__new__(Local);handler.path='/api/bookings/PRIVATE-ID?token=SECRET';handler.command='GET';handler.wfile=BytesIO()
        return handler

    def test_completed_native_and_wsgi_request_emit_one_private_safe_timing_record(self):
        for hosted in (False,True):
            with self.subTest(hosted=hosted):
                handler=self.handler(hosted);stream=StringIO()
                def success():handler.reply(200,{'private':'response stays out of logs'})
                with patch.object(handler,'handle_request',success), patch.object(server.time,'monotonic',side_effect=[10,10.125]), redirect_stdout(stream):
                    handler.dispatch()
                lines=stream.getvalue().splitlines();self.assertEqual(len(lines),1)
                self.assertEqual(json.loads(lines[0]),{'event':'http','method':'GET','group':'bookings','status':200,'durationMs':125.0,'outcome':'ok'})
                self.assertNotIn('PRIVATE',lines[0]);self.assertNotIn('SECRET',lines[0]);self.assertNotIn('response stays',lines[0])

    def test_sqlite_contention_is_retryable_but_other_failures_remain_generic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'db.sqlite3'
            with closing(sqlite3.connect(path)) as writer, closing(sqlite3.connect(path,timeout=.001)) as reader:
                writer.execute('CREATE TABLE item(value)');writer.commit();writer.execute('BEGIN IMMEDIATE')
                try:reader.execute('INSERT INTO item VALUES(1)')
                except sqlite3.OperationalError as error:busy=error
                else:self.fail('Expected real SQLite writer contention')
                for error,status,outcome in [(busy,503,'database_busy'),
                                             (sqlite3.OperationalError('PRIVATE path SECRET SQL'),500,'server_error'),
                                             (RuntimeError('PRIVATE body SECRET token'),500,'server_error'),
                                             (ConnectionResetError('SECRET peer'),0,'disconnected')]:
                    handler=self.handler(True);stream=StringIO()
                    with patch.object(handler,'handle_request',side_effect=error), redirect_stdout(stream):handler.dispatch()
                    record=json.loads(stream.getvalue());self.assertEqual(record['outcome'],outcome)
                    self.assertEqual(record['status'],status)
                    self.assertNotIn('SECRET',stream.getvalue());self.assertNotIn('PRIVATE',stream.getvalue())
                    if outcome!='disconnected':
                        self.assertEqual(handler.response_status,status)
                        self.assertNotIn(b'SECRET',handler.wfile.getvalue())
                writer.rollback()

    def test_invalid_metric_values_are_normalized_without_dynamic_labels(self):
        for elapsed in (-1, float('nan'), float('inf'), 'SECRET', True):
            record=json.loads(access_record('GET','/api/ready',503,elapsed_seconds=elapsed,outcome='SECRET outcome'))
            self.assertIsNone(record['durationMs']);self.assertEqual(record['outcome'],'server_error')
            self.assertNotIn('SECRET',json.dumps(record))
        self.assertEqual(json.loads(access_record('GET','/api/admin/work-queue?owner=PRIVATE',200,elapsed_seconds=1))['group'],'admin/work-queue')

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
