from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest
import backup_bundle
import test_booking_videos
import server


class BackupBundleTests(unittest.TestCase):
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

    def test_bundle_restore_contains_referenced_media_and_detects_corruption(self):
        b=self.active();self.upload(b,self.data(),self.source())
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'snapshot'
            self.assertEqual(backup_bundle.create(server.DATA,target),{'database':'ok','mediaFiles':2})
            with closing(sqlite3.connect(target/'momiq.sqlite3')) as con:
                self.assertEqual(con.execute('SELECT COUNT(*) FROM booking_videos').fetchone()[0],1)
                self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(),[])
            with self.assertRaises(ValueError):backup_bundle.create(server.DATA,target)
            next(target.glob('care-videos/*/playback.mp4')).write_bytes(b'corrupt')
            with self.assertRaises(ValueError):backup_bundle.verify(target)

    def test_incomplete_copy_is_never_published_and_does_not_touch_source(self):
        b=self.active();saved=self.upload(b,self.data(),self.source())
        video=server.DATA/'care-videos'/saved['id']/'playback.mp4'
        original=video.read_bytes();video.write_bytes(b'corrupt TEST fixture')
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'snapshot'
            with self.assertRaises(ValueError):backup_bundle.create(server.DATA,target)
            self.assertFalse(target.exists());self.assertEqual(list(Path(folder).iterdir()),[])
        video.write_bytes(original)
