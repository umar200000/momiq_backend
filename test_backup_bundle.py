from pathlib import Path
from contextlib import closing
import sqlite3
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
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

    def test_backup_rotation_never_keeps_video_beyond_its_approved_expiry(self):
        b=self.active();self.upload(b,self.data(),self.source())
        end=self.start+timedelta(hours=2)
        b=self.act(b,'complete',user='customer',now=end);self.act(b,'complete',now=end)
        captured=end+timedelta(days=29)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);target=root/'20261201T000000Z-1234abcd'
            with patch.object(backup_bundle,'datetime',wraps=datetime) as clock:
                clock.now.return_value=captured
                backup_bundle.create(server.DATA,target)
            self.assertEqual(backup_bundle.bundle_expiry(target),end+timedelta(days=30))
            self.assertEqual(backup_bundle.prune(root,end+timedelta(days=30,microseconds=-1))['removed'],0)
            self.assertEqual(backup_bundle.prune(root,end+timedelta(days=30)),{'removed':1,'failed':0})
            self.assertFalse(target.exists())

    def test_rotation_preserves_unknown_files_and_custom_backup_names(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);target=root/'20261028T000000Z-1234abcd'
            backup_bundle.create(server.DATA,target)
            (target/'user-notes.txt').write_text('TEST preserve')
            custom=root/'manual-preserve';backup_bundle.create(server.DATA,custom)
            result=backup_bundle.prune(root,datetime.now(timezone.utc)+timedelta(days=15))
            self.assertEqual(result,{'removed':0,'failed':1})
            self.assertTrue((target/'user-notes.txt').exists());self.assertTrue(custom.exists())

    def test_bundle_restore_contains_referenced_media_and_detects_corruption(self):
        import restore_drill
        import wallet
        with server.db() as con:
            # Replace this fixture's synthetic opening balance with a journalled one.
            self.assertEqual(con.execute("SELECT COUNT(*) FROM wallet_entries").fetchone()[0], 0)
            con.execute("UPDATE wallet_accounts SET balance_minor=0 WHERE user_id='abc'")
            wallet.post_entry(con,'abc',100000000,'topup','TEST-drill','operator','TEST recovery credit')
        b=self.active();self.upload(b,self.data(),self.source())
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'snapshot'
            self.assertEqual(backup_bundle.create(server.DATA,target),{'database':'ok','mediaFiles':2})
            result=restore_drill.rehearse(target,server.ENVIRONMENT)
            self.assertEqual(result['mediaFiles'],2)
            self.assertTrue(result['reconciled'])
            if shutil.which('age') and shutil.which('age-keygen'):
                import encrypted_backup
                key = Path(folder)/'recovery-identity'
                subprocess.run(['age-keygen','-o',str(key)],capture_output=True,check=True)
                recipient = subprocess.check_output(['age-keygen','-y',str(key)],text=True).strip()
                encrypted = Path(folder)/'recovery.age'
                proof = encrypted_backup.seal(target,encrypted,recipient)
                restored = encrypted_backup.drill(encrypted,key,proof['sha256'],server.ENVIRONMENT)
                self.assertEqual((restored['mediaFiles'],restored['reconciled']),(2,True))
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
