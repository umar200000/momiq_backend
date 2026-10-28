from datetime import timedelta
from io import BytesIO
import secrets
import hashlib
import json
import time
import sqlite3
import subprocess
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from urllib.parse import urlencode

import booking_care
import booking_videos as videos
import server
import test_booking_care
import video_media


class BookingVideoTests(unittest.TestCase):
    setUp = test_booking_care.BookingCareTests.setUp
    save = test_booking_care.BookingCareTests.save
    review = test_booking_care.BookingCareTests.review
    quote = test_booking_care.BookingCareTests.quote
    request = test_booking_care.BookingCareTests.request
    act = test_booking_care.BookingCareTests.act
    accepted = test_booking_care.BookingCareTests.accepted
    active = test_booking_care.BookingCareTests.active
    expect_error = test_booking_care.BookingCareTests.expect_error

    def source(self):
        path = server.DATA/'fixture.mp4'
        subprocess.run([video_media.executable('ffmpeg'),'-v','error','-f','lavfi','-i','color=c=blue:s=128x96:r=24',
                        '-t','10','-c:v','libx264','-pix_fmt','yuv420p','-y',str(path)],check=True,timeout=20,
                       creationflags=subprocess.CREATE_NO_WINDOW if video_media.os.name=='nt' else 0)
        return path

    def data(self, **changes):
        return dict({'petId':'cat-a','day':booking_care.today(self.start),'slot':'evening','requestId':secrets.token_hex(16)},**changes)

    def upload(self, b, data, source, user='abc', clock=None):
        with server.db() as con:
            return videos.store(con,server.DATA,b['id'],user,data,source,clock or (lambda:self.start+timedelta(hours=1)))

    def test_real_upload_retry_private_playback_and_immutable_slot(self):
        b=self.active();source=self.source();data=self.data()
        first=self.upload(b,data,source)
        # A lost response can be retried after the window; same bytes/identity only.
        self.assertEqual(first,self.upload(b,data,source,clock=lambda:self.start+timedelta(days=1)))
        self.expect_error(409,lambda:self.upload(b,self.data(),source))
        source.write_bytes(source.read_bytes()+b'changed')
        self.expect_error(409,lambda:self.upload(b,data,source))
        with server.db() as con:
            result=videos.overview(con,b['id'],'customer',data['day'],self.start+timedelta(hours=1))
            self.assertFalse(result['canUpload']);self.assertEqual(result['items'],[dict(first,available=True,expiresAt=None)])
            self.assertEqual(con.execute('SELECT COUNT(*) FROM booking_videos').fetchone()[0],1)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM notifications WHERE source_key LIKE 'care-video:%'").fetchone()[0],1)
            with self.assertRaises(sqlite3.IntegrityError):con.execute("UPDATE booking_videos SET day='2026-01-01'")
        class Handler:
            headers={'Range':'bytes=0-15'};wfile=BytesIO();response={}
            def send_response(self,status):self.status=status
            def send_header(self,key,value):self.response[key]=value
            def end_headers(self):pass
        h=Handler()
        with server.db() as con:
            videos.download(h,con,server.DATA,b['id'],'customer',first['id'],'playback')
        self.assertEqual(h.status,206);self.assertEqual(len(h.wfile.getvalue()),16)
        self.assertEqual(h.response['Cache-Control'],'private, no-store')
        with server.db() as con:
            self.expect_error(404,lambda:videos.download(h,con,server.DATA,b['id'],'stranger',first['id'],'playback'))

    def test_clock_role_pet_and_final_state_rechecked_before_commit(self):
        b=self.active();source=self.source();data=self.data()
        self.expect_error(403,lambda:self.upload(b,data,source,user='customer'))
        self.expect_error(404,lambda:self.upload(b,self.data(petId='cat-b'),source))
        with self.assertRaises(ValueError):self.upload(b,data,source,clock=lambda:self.start)
        with self.assertRaises(ValueError):self.upload(b,self.data(day='2020-01-01'),source)
        calls=iter([self.start+timedelta(hours=1),self.start+timedelta(hours=5)])
        with self.assertRaises(ValueError):self.upload(b,data,source,clock=lambda:next(calls))
        original=video_media.prepare
        def complete_after_decode(*args):
            result=original(*args)
            with server.db() as con:con.execute("UPDATE bookings SET status='completed' WHERE id=?",(b['id'],))
            return result
        with patch.object(video_media,'prepare',side_effect=complete_after_decode):
            self.expect_error(403,lambda:self.upload(b,data,source))
        with server.db() as con:self.assertEqual(con.execute('SELECT COUNT(*) FROM booking_videos').fetchone()[0],0)
        self.assertEqual(list((server.DATA/'care-videos').iterdir()),[])

    def test_failure_rolls_back_files_notice_and_report(self):
        b=self.active();source=self.source()
        with patch.object(videos.notifications,'publish',side_effect=RuntimeError('TEST failure')):
            with self.assertRaises(RuntimeError):self.upload(b,self.data(),source)
        with server.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM booking_videos').fetchone()[0],0)
        self.assertEqual(list((server.DATA/'care-videos').iterdir()),[])

    def test_simultaneous_exact_retries_commit_one_report_and_directory(self):
        b=self.active();source=self.source();data=self.data()
        barrier=threading.Barrier(2);original=video_media.prepare
        def prepare(*args):
            result=original(*args);barrier.wait(timeout=15);return result
        with patch.object(video_media,'prepare',side_effect=prepare), ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(self.upload,b,data,source) for _ in range(2)]
            results=[f.result(timeout=30) for f in futures]
        self.assertEqual(results[0],results[1])
        self.assertEqual(len(list((server.DATA/'care-videos').iterdir())),1)
        with server.db() as con:self.assertEqual(con.execute('SELECT COUNT(*) FROM booking_videos').fetchone()[0],1)

    def test_binary_route_query_size_partial_upload_and_range_validation(self):
        b=self.active();source=self.source();data=self.data()
        class Handler:
            command='POST'
            def reply(self,status,body):self.status,self.result=status,body
        def send(raw, length=None):
            h=Handler();h.path=f"/api/bookings/{b['id']}/videos?"+urlencode(data)
            h.headers={'Content-Type':'video/mp4','Content-Length':str(len(raw) if length is None else length)}
            h.rfile=BytesIO(raw)
            with server.db() as con:
                videos.route(h,con,'abc',h.path.split('?')[0],server.DATA,lambda:self.start+timedelta(hours=1))
            return h
        self.expect_error(413,lambda:send(b'',33554433))
        with self.assertRaises(ValueError):send(b'partial video',100)
        h=send(source.read_bytes());self.assertEqual(h.status,200)
        for header in ('bytes=999-','bytes=2-1','bytes=-0','bytes=0-1,3-5','garbage'):
            self.expect_error(416,lambda:videos.byte_range(header,100))
        self.assertEqual(videos.byte_range('bytes=-10',100),(90,99,206))
        self.assertEqual(videos.byte_range('bytes=10-',100),(10,99,206))

    def test_wsgi_upload_and_range_require_participant_bearer_session(self):
        from wsgi import application
        from wsgiref.util import setup_testing_defaults
        b=self.active();source=self.source();data=self.data()
        with server.db() as con:
            for user in ['abc','customer','stranger']:
                con.execute('INSERT INTO sessions VALUES(?,?,?,?)',
                    (hashlib.sha256(('TEST-'+user).encode()).hexdigest(),user,'client',time.time()+60))
            con.execute('INSERT INTO sessions VALUES(?,?,?,?)',
                (hashlib.sha256(b'TEST-admin').hexdigest(),'admin','admin',time.time()+60))
        def call(method,path,query='',raw=b'',user=None,byte_range=None,admin=False):
            env={};setup_testing_defaults(env)
            env.update(REQUEST_METHOD=method,PATH_INFO=path,QUERY_STRING=query,
                       CONTENT_LENGTH=str(len(raw)),CONTENT_TYPE='video/mp4')
            env['wsgi.input']=BytesIO(raw)
            if user:env['HTTP_AUTHORIZATION']='Bearer TEST-'+user
            if byte_range:env['HTTP_RANGE']=byte_range
            if admin:env['HTTP_COOKIE']='momiq_admin=TEST-admin'
            response={}
            def start(status,headers):response.update(status=int(status.split()[0]),headers=dict(headers))
            response['body']=b''.join(application(env,start));return response
        path=f"/api/bookings/{b['id']}/videos"
        with patch.object(videos,'datetime') as clock:
            clock.now.return_value=self.start+timedelta(hours=1)
            self.assertEqual(call('POST',path,urlencode(data),source.read_bytes())['status'],401)
            self.assertEqual(call('POST',path,urlencode(data),source.read_bytes(),'customer')['status'],403)
            uploaded=call('POST',path,urlencode(data),source.read_bytes(),'abc')
            self.assertEqual(uploaded['status'],200,uploaded['body'])
            video=json.loads(uploaded['body'])['id']
            playback=path+'/'+video+'/playback'
            self.assertEqual(call('GET',playback,user='stranger')['status'],404)
            response=call('GET',playback,user='customer',byte_range='bytes=0-11')
            self.assertEqual(response['status'],206);self.assertEqual(len(response['body']),12)
            self.assertEqual(response['body'][4:8],b'ftyp')
            self.assertEqual(response['headers']['Cache-Control'],'private, no-store')
            admin_path='/api/admin/bookings/'+b['id']+'/videos'
            self.assertEqual(call('GET',admin_path,user='customer')['status'],401)
            overview=call('GET',admin_path,query=urlencode({'day':data['day']}),admin=True)
            self.assertEqual(overview['status'],200,overview['body'])
            self.assertFalse(json.loads(overview['body'])['canUpload'])
            media=call('GET',admin_path+'/'+video+'/poster',admin=True)
            self.assertEqual(media['status'],200);self.assertEqual(media['headers']['Vary'],'Cookie')
            self.assertEqual(call('DELETE',admin_path,admin=True)['status'],405)
            with server.db() as con:
                self.assertEqual(con.execute("SELECT COUNT(*) FROM audit WHERE action IN ('admin-view-booking-videos','admin-view-booking-video')").fetchone()[0],2)
