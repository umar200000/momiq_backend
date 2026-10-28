from datetime import timedelta, datetime
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import secrets
import unittest

import backup_bundle
import booking_disputes
import booking_videos
import media_maintenance
import server
import test_booking_videos
import video_retention as retention


class VideoRetentionTests(unittest.TestCase):
    setUp=test_booking_videos.BookingVideoTests.setUp
    save=test_booking_videos.BookingVideoTests.save
    review=test_booking_videos.BookingVideoTests.review
    quote=test_booking_videos.BookingVideoTests.quote
    request=test_booking_videos.BookingVideoTests.request
    act=test_booking_videos.BookingVideoTests.act
    accepted=test_booking_videos.BookingVideoTests.accepted
    active=test_booking_videos.BookingVideoTests.active
    source=test_booking_videos.BookingVideoTests.source
    data=test_booking_videos.BookingVideoTests.data
    upload=test_booking_videos.BookingVideoTests.upload
    expect_error=test_booking_videos.BookingVideoTests.expect_error

    def finish(self,b,now):
        b=self.act(b,'complete',user='customer',now=now)
        return self.act(b,'complete',now=now)

    def cleanup(self,now):
        with server.db() as con:return retention.cleanup(con,server.DATA,now)

    def test_exact_30_day_boundary_denies_access_before_job_and_purges_once(self):
        b=self.active();video=self.upload(b,self.data(),self.source())
        end=self.start+timedelta(hours=2);self.finish(b,end)
        expiry=end+timedelta(days=30)
        with server.db() as con:
            row=con.execute('SELECT * FROM booking_videos WHERE id=?',(video['id'],)).fetchone()
            self.assertTrue(retention.status(con,row,expiry-timedelta(microseconds=1))['available'])
            self.assertFalse(retention.status(con,row,expiry)['available'])
            with patch.object(booking_videos,'datetime',wraps=datetime) as clock:
                clock.now.return_value=expiry
                self.expect_error(410,lambda:booking_videos.download(None,con,server.DATA,b['id'],'customer',video['id'],'playback'))
        self.assertEqual(self.cleanup(expiry),{'retired':1,'purged':1,'failed':0})
        self.assertEqual(self.cleanup(expiry),{'retired':0,'purged':0,'failed':0})
        self.assertFalse((server.DATA/'care-videos'/video['id']).exists())
        with server.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM booking_videos').fetchone()[0],1)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM audit WHERE action='video-purged'").fetchone()[0],1)

    def test_open_dispute_holds_media_and_resolution_starts_new_30_days(self):
        b=self.active();video=self.upload(b,self.data(),self.source())
        with server.db() as con:
            case=booking_disputes.write(con,b['id'],'customer',{'action':'report','kind':'service','revision':0,
                'bookingRevision':b['revision'],'text':'TEST only','image':None,'requestId':secrets.token_hex(16)},
                lambda image:image,self.start+timedelta(hours=2),'local')
        self.assertEqual(self.cleanup(self.start+timedelta(days=45))['retired'],0)
        resolved=self.start+timedelta(days=50)
        with server.db() as con:
            revision=con.execute('SELECT revision FROM bookings WHERE id=?',(b['id'],)).fetchone()[0]
            booking_disputes.resolve(con,b['id'],'admin',{'revision':1,'bookingRevision':revision,
                'requestId':secrets.token_hex(16),'outcome':'cancel_service','reason':'TEST resolved',
                'fault':'none','emergency':False,'refundMinor':0},resolved,'local')
        self.assertEqual(self.cleanup(resolved+timedelta(days=30,microseconds=-1))['retired'],0)
        self.assertTrue((server.DATA/'care-videos'/video['id']).exists())
        self.assertEqual(self.cleanup(resolved+timedelta(days=30))['purged'],1)

    def test_failed_file_cleanup_retries_without_republishing_or_deleting_unknown_file(self):
        b=self.active();video=self.upload(b,self.data(),self.source())
        end=self.start+timedelta(hours=2);self.finish(b,end)
        folder=server.DATA/'care-videos'/video['id'];unknown=folder/'unrelated.txt'
        unknown.write_text('TEST preserve')
        self.assertEqual(self.cleanup(end+timedelta(days=30)),{'retired':1,'purged':0,'failed':1})
        self.assertTrue(unknown.is_file());self.assertTrue((folder/'playback.mp4').is_file())
        unknown.unlink()
        self.assertEqual(self.cleanup(end+timedelta(days=31)),{'retired':0,'purged':1,'failed':0})

    def test_backups_exclude_expired_files_even_before_cleanup(self):
        b=self.active();self.upload(b,self.data(),self.source())
        end=self.start+timedelta(hours=2);self.finish(b,end)
        database=server.DATA/'momiq.sqlite3'
        self.assertEqual(len(backup_bundle.references(database,end)),2)
        self.assertEqual(backup_bundle.references(database,end+timedelta(days=30)),[])

    def test_backup_and_cleanup_share_exclusive_cross_handle_lock(self):
        def acquire():
            with media_maintenance.lock(server.DATA,timeout=.1):return True
        with ThreadPoolExecutor(max_workers=1) as pool:
            with media_maintenance.lock(server.DATA):
                with self.assertRaises(TimeoutError):pool.submit(acquire).result(timeout=3)
            self.assertTrue(pool.submit(acquire).result(timeout=3))
