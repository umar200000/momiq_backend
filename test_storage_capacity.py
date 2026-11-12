from datetime import timedelta
from email.message import Message
import errno
from io import BytesIO, StringIO
from contextlib import redirect_stdout
import re
import secrets
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import booking_videos
import server
import storage_capacity as storage
import test_api
import test_booking_videos as fixtures
from test_media import fixture_image
from tool import instance_report


class CapacityTests(unittest.TestCase):
    def test_exact_reserve_boundary_and_unavailable_disk(self):
        for free, allowed in ((storage.RESERVE_BYTES+100, True), (storage.RESERVE_BYTES+99, False)):
            with patch.object(storage.shutil, 'disk_usage', return_value=SimpleNamespace(free=free)):
                if allowed:
                    storage.require_space('.', 100)
                else:
                    with self.assertRaises(storage.StorageUnavailable): storage.require_space('.', 100)
        with patch.object(storage.shutil, 'disk_usage', side_effect=OSError('PRIVATE path')):
            with self.assertRaises(storage.StorageUnavailable) as raised: storage.require_space('.', 0)
        self.assertNotIn('PRIVATE', str(raised.exception))
        for value in (True, -1, 1.5):
            with self.assertRaises(ValueError): storage.require_space('.', value)


class ReceiptCapacityTests(unittest.TestCase):
    setUpClass=classmethod(test_api.ApiTests.setUpClass.__func__)
    tearDownClass=classmethod(test_api.ApiTests.tearDownClass.__func__)
    setUp=test_api.ApiTests.setUp
    req=test_api.ApiTests.req

    def test_low_disk_preserves_request_and_amend_retry_evidence(self):
        login=self.req('/api/auth/login','POST',{'phone':'998900111551','code':'111111','role':'sitter'})
        config=self.req('/api/admin/platform-settings',admin=True)
        config=self.req('/api/admin/platform-settings','PUT',dict(version=config['version'],qrImage=fixture_image('cyan'),qrActive=True,recipientName='TEST ONLY',reason='TEST storage'),admin=True)
        body={'requestId':secrets.token_hex(16),'amountMinor':100,'receipt':fixture_image('cyan'),'qrVersion':config['version'],'termsVersion':'balance-no-refund-v1','acceptNonRefundable':True,'payerReference':'TEST capacity'}
        with server.db() as con: before=list(con.iterdump())
        with patch.object(storage, 'require_space', side_effect=storage.StorageUnavailable()) as guard:
            self.req('/api/wallet/topups','POST',body,token=login['token'],expected=503)
            self.assertEqual(guard.call_args.args[0],server.DATA)
        with server.db() as con: self.assertEqual(list(con.iterdump()),before)
        original=self.req('/api/wallet/topups','POST',body,token=login['token'],expected=201)
        tid=original['topup']['id']
        self.req('/api/admin/topups/'+tid+'/review','POST',{'revision':0,'decision':'request_info','reason':'TEST storage clarification'},admin=True)
        changed=dict(body,requestId=secrets.token_hex(16),revision=1,receipt=fixture_image('pink'))
        with server.db() as con: before=list(con.iterdump())
        with patch.object(storage, 'require_space', side_effect=storage.StorageUnavailable()):
            self.req('/api/wallet/topups/'+tid+'/amend','POST',changed,token=login['token'],expected=503)
        with server.db() as con: self.assertEqual(list(con.iterdump()),before)
        amended=self.req('/api/wallet/topups/'+tid+'/amend','POST',changed,token=login['token'])
        with patch.object(storage, 'require_space', side_effect=AssertionError('exact retry must not allocate')):
            retry=self.req('/api/wallet/topups/'+tid+'/amend','POST',changed,token=login['token'])
            first=self.req('/api/wallet/topups','POST',body,token=login['token'])
        self.assertEqual(retry['acknowledgement'],amended['acknowledgement'])
        self.assertEqual(first['acknowledgement'],original['acknowledgement'])
        with server.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM wallet_entries').fetchone()[0],0)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM topup_evidence_claims WHERE topup_id=?',(tid,)).fetchone()[0],2)

    def test_storage_failures_are_retryable_without_private_error_details(self):
        full=sqlite3.OperationalError('PRIVATE database path');full.sqlite_errorcode=sqlite3.SQLITE_FULL
        for error in (full,OSError(errno.ENOSPC,'PRIVATE disk'),OSError(errno.EDQUOT,'PRIVATE quota'),storage.StorageUnavailable()):
            with patch.object(server.Handler,'handle_request',side_effect=error),redirect_stdout(StringIO()) as log:
                reply=self.req('/api/health',expected=503)
            self.assertEqual(reply,{'error':storage.UNAVAILABLE})
            self.assertNotIn('PRIVATE',log.getvalue())
            self.assertIn('storage_busy',log.getvalue())


class VideoCapacityTests(unittest.TestCase):
    setUp=fixtures.BookingVideoTests.setUp
    save=fixtures.BookingVideoTests.save
    review=fixtures.BookingVideoTests.review
    quote=fixtures.BookingVideoTests.quote
    request=fixtures.BookingVideoTests.request
    act=fixtures.BookingVideoTests.act
    accepted=fixtures.BookingVideoTests.accepted
    active=fixtures.BookingVideoTests.active
    source=fixtures.BookingVideoTests.source
    data=fixtures.BookingVideoTests.data
    upload=fixtures.BookingVideoTests.upload

    def test_low_capacity_before_decode_and_publication_preserves_database(self):
        booking=self.active();source=self.source();data=self.data()
        with server.db() as con: before=list(con.iterdump())
        for effects in ([storage.StorageUnavailable()], [None,storage.StorageUnavailable()]):
            with patch.object(storage,'require_space',side_effect=effects):
                with self.assertRaises(storage.StorageUnavailable): self.upload(booking,data,source)
            with server.db() as con: self.assertEqual(list(con.iterdump()),before)
            root=server.DATA/'care-videos'
            self.assertFalse(root.exists() and list(root.iterdir()))
        saved=self.upload(booking,data,source)
        with patch.object(storage,'require_space',side_effect=AssertionError('stored retry does not allocate')):
            self.assertEqual(self.upload(booking,data,source),saved)

    def test_receive_refuses_before_reading_body_or_charging_quota(self):
        booking=self.active();data=self.data()
        handler=SimpleNamespace(headers=Message(),rfile=BytesIO(b'TEST source'),close_connection=False)
        handler.headers['Content-Type']='video/mp4';handler.headers['Content-Length']='12'
        match=re.fullmatch(r'/api/bookings/([a-f0-9]{32})/videos',f"/api/bookings/{booking['id']}/videos")
        with server.db() as con:
            before=list(con.iterdump())
            with patch.object(storage,'require_space',side_effect=storage.StorageUnavailable()):
                with self.assertRaises(storage.StorageUnavailable):
                    booking_videos.receive(handler,con,'abc',match,{k:[v] for k,v in data.items()},server.DATA,lambda:self.start+timedelta(hours=1))
            self.assertEqual(list(con.iterdump()),before)
        self.assertTrue(handler.close_connection)
        self.assertEqual(handler.rfile.tell(),0)
        self.assertFalse((server.DATA/'care-videos').exists())

    def test_disk_full_during_publication_removes_partial_files_and_allows_retry(self):
        booking=self.active();source=self.source();data=self.data()
        with server.db() as con: before=list(con.iterdump())
        def partial_copy(incoming, outgoing):
            outgoing.write(b'TEST incomplete')
            raise OSError(errno.ENOSPC, 'TEST full disk')
        with patch.object(booking_videos.shutil,'copyfileobj',side_effect=partial_copy):
            with self.assertRaises(OSError) as raised: self.upload(booking,data,source)
        self.assertEqual(raised.exception.errno,errno.ENOSPC)
        self.assertEqual(list((server.DATA/'care-videos').iterdir()),[])
        self.assertTrue(source.exists())
        with server.db() as con: self.assertEqual(list(con.iterdump()),before)
        saved=self.upload(booking,data,source)
        self.assertEqual(self.upload(booking,data,source),saved)

    def test_video_metrics_distinguish_pending_purge_and_do_not_touch_files(self):
        booking=self.active();saved=self.upload(booking,self.data(),self.source())
        def snapshot(): return instance_report.snapshot(server.DATA,server.ENVIRONMENT)
        first=snapshot()
        self.assertEqual(first['unpurgedVideoCount'],1)
        self.assertGreater(first['unpurgedVideoRecordedBytes'],0)
        self.assertEqual(first['pendingVideoPurgeCount'],0)
        with server.db() as con:
            con.execute('INSERT INTO video_retirements VALUES(?,?,NULL)',(saved['id'],self.start.isoformat()))
        self.assertEqual(snapshot()['pendingVideoPurgeCount'],1)
        with server.db() as con:
            con.execute('UPDATE video_retirements SET purged_at=?',(self.start.isoformat(),))
            before=list(con.iterdump())
        result=snapshot()
        self.assertEqual(result['unpurgedVideoRecordedBytes'],0)
        self.assertEqual(result['unpurgedVideoCount'],0)
        self.assertEqual(result['pendingVideoPurgeCount'],0)
        # Metadata measurement deliberately does not assert physical file deletion.
        self.assertTrue((server.DATA/'care-videos'/saved['id']/'playback.mp4').exists())
        with server.db() as con: self.assertEqual(list(con.iterdump()),before)


if __name__=='__main__': unittest.main()
