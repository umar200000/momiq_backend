import io
import json
import threading
import unittest
from email.message import Message
from types import SimpleNamespace
from unittest.mock import patch
import request_json as body
from server import Handler
from wsgi import WsgiHandler


class JsonBodyTests(unittest.TestCase):
    def handler(self,raw=b'{}',**headers):
        message=Message();message['Content-Length']=str(len(raw));message['Content-Type']='application/json; charset=utf-8'
        for key,value in headers.items():
            del message[key];message[key]=value
        return SimpleNamespace(headers=message,rfile=io.BytesIO(raw))

    def test_duplicate_keys_nonfinite_numbers_encoding_and_nonobject_rejected(self):
        for raw in (b'{"a":1,"a":2}',b'{"a":1,"\\u0061":2}',b'{"x":{"a":0,"a":1}}',b'{"x":NaN}',b'{"x":Infinity}',b'{"x":-Infinity}',b'{"x":1e9999}',b'[]',b'null',b'{"x":"\xff"}',b'{} trailing'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):body.read(self.handler(raw))
        self.assertEqual(body.read(self.handler('{"ism":"O‘tkir","x":1.5}'.encode())),{'ism':'O‘tkir','x':1.5})

    def test_nesting_bounded_before_decode_but_escaped_strings_are_ordinary_data(self):
        valid=b'{"v":'+b'['*63+b'0'+b']'*63+b'}'
        self.assertIn('v',body.read(self.handler(valid)))
        excessive=b'{"v":'+b'['*64+b'0'+b']'*64+b'}'
        with patch.object(body.json,'loads',side_effect=AssertionError('decoder must not run')):
            with self.assertRaises(ValueError):body.read(self.handler(excessive))
        value='['*1000+'\\"'+']'*1000
        self.assertEqual(body.decode(json.dumps({'value':value}).encode()),{'value':value})

    def test_framing_exact_mime_and_oversize_fail_before_read(self):
        for headers,status in (({'Content-Length':'-1'},400),({'Content-Length':'2,2'},400),({'Content-Length':'32000001'},413),({'Content-Length':'0'},413),({'Content-Type':'application/jsonp'},415),({'Transfer-Encoding':'chunked'},400)):
            h=self.handler(**headers)
            with patch.object(h.rfile,'read1',side_effect=AssertionError('must not read')):
                with self.assertRaises(body.BodyError) as caught:body.read(h)
            self.assertEqual(caught.exception.status,status)
        for header in ('Content-Length','Content-Type'):
            h=self.handler();h.headers[header]=h.headers[header]
            with self.assertRaises(body.BodyError):body.read(h)

    def test_partial_reads_truncation_timeout_and_reader_release(self):
        class Partial(io.BytesIO):
            def read1(self,size):return super().read(min(size,1))
        h=self.handler(b'{"x":1}');h.rfile=Partial(b'{"x":1}')
        self.assertEqual(body.read(h),{'x':1})
        h=self.handler(b'{"x":1}',**{'Content-Length':'9'})
        with self.assertRaises(body.BodyError) as caught:Handler.body(h)
        self.assertEqual(caught.exception.status,400);self.assertTrue(h.close_connection)
        h=self.handler()
        with patch.object(h.rfile,'read1',side_effect=TimeoutError):
            with self.assertRaises(body.BodyError) as caught:Handler.body(h)
        self.assertEqual(caught.exception.status,408);self.assertTrue(h.close_connection)
        self.assertEqual(body.read(self.handler()),{})

    def test_wsgi_uses_same_strict_parser(self):
        h=WsgiHandler({'REQUEST_METHOD':'POST','PATH_INFO':'/api/auth/login','CONTENT_LENGTH':'13','CONTENT_TYPE':'application/json','wsgi.input':io.BytesIO(b'{"a":1,"a":2}')})
        with self.assertRaises(ValueError):h.body()
        self.assertTrue(h.close_connection)

    def test_total_deadline_socket_timeout_restore_and_busy_rejection(self):
        class Socket:
            timeout=None
            def gettimeout(self):return self.timeout
            def settimeout(self,value):self.timeout=value
        h=self.handler();h.connection=Socket()
        with patch.object(body.time,'monotonic',side_effect=[0,1,61]):
            with self.assertRaises(body.BodyError) as caught:Handler.body(h)
        self.assertEqual(caught.exception.status,408)
        self.assertIsNone(h.connection.timeout)
        with patch.object(body._readers,'acquire',return_value=False):
            with self.assertRaises(body.BodyError) as caught:Handler.body(self.handler())
        self.assertEqual(caught.exception.status,503)

    def test_socket_timeout_read_failure_does_not_consume_reader_capacity(self):
        class ClosedSocket:
            def gettimeout(self):raise OSError('TEST closed descriptor')
        h=self.handler();h.connection=ClosedSocket()
        with patch.object(body,'_readers',threading.BoundedSemaphore(1)):
            with self.assertRaises(OSError):body.read(h)
            self.assertEqual(body.read(self.handler()),{})

    def test_closed_socket_on_timeout_restore_preserves_body_error_and_capacity(self):
        class ClosingSocket:
            def gettimeout(self):return None
            def settimeout(self,value):
                if value is None:raise OSError('TEST closed descriptor')
        h=self.handler(b'{',**{'Content-Length':'2'});h.connection=ClosingSocket()
        with patch.object(body,'_readers',threading.BoundedSemaphore(1)):
            with self.assertRaises(body.BodyError) as caught:Handler.body(h)
            self.assertEqual(caught.exception.status,400)
            self.assertTrue(h.close_connection)
            self.assertEqual(body.read(self.handler()),{})

    def test_successful_body_with_closed_restore_closes_connection_without_capacity_loss(self):
        class ClosingSocket:
            def gettimeout(self):return None
            def settimeout(self,value):
                if value is None:raise OSError('TEST closed descriptor')
        h=self.handler();h.connection=ClosingSocket()
        with patch.object(body,'_readers',threading.BoundedSemaphore(1)):
            self.assertEqual(Handler.body(h),{})
            self.assertTrue(h.close_connection)
            self.assertEqual(body.read(self.handler()),{})


if __name__=='__main__':unittest.main()
