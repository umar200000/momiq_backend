from pathlib import Path
import os
import tempfile
import time
import unittest
from unittest.mock import patch

import media_maintenance
import media_reconcile
import server


class ReconcileTests(unittest.TestCase):
    def test_dry_run_purge_and_wrong_instance(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            with patch.object(server, 'DATA', data), patch.object(server, 'ENVIRONMENT', 'test'):
                server.setup()
            root = data/'care-videos'
            root.mkdir()
            old = time.time() - 3*86400
            for index in range(4):
                folder = root/f'{index:032x}'
                folder.mkdir()
                member = folder/('unknown' if index == 2 else 'poster.jpg')
                member.write_bytes(b'TEST')
                if index < 3:
                    os.utime(member,(old,old))
                    os.utime(folder,(old,old))
            (root/'.upload-active').mkdir()
            protected = data/'unrelated-evidence'
            protected.write_bytes(b'KEEP')
            linked_dir = root/('e'*32)
            linked_dir.mkdir()
            os.link(protected,linked_dir/'poster.jpg')
            initial = media_reconcile.reconcile(data, 'test')
            self.assertEqual(initial, dict(orphan=2, temporary=1, recent=1, referenced=0, unsafe=2, purged=0,
                                           abandoned=0, temporaryPurged=0))
            with self.assertRaises(ValueError):
                media_reconcile.reconcile(data, 'production', purge=True)
            self.assertEqual(media_reconcile.reconcile(data, 'test', purge=True, limit=1)['purged'], 1)
            self.assertEqual(media_reconcile.reconcile(data, 'test', purge=True)['purged'], 1)
            self.assertEqual(media_reconcile.reconcile(data, 'test', purge=True)['purged'], 0)
            self.assertTrue((root/f'{2:032x}'/'unknown').is_file())
            self.assertTrue((root/'.upload-active').is_dir())
            self.assertEqual(protected.read_bytes(),b'KEEP')
            self.assertTrue((linked_dir/'poster.jpg').is_file())

    def test_old_but_live_upload_cannot_be_purged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(server,'DATA',root), patch.object(server,'ENVIRONMENT','test'):
                server.setup()
            videos = root/'care-videos'
            videos.mkdir()
            folder = videos/'.upload-synthetic'
            folder.mkdir()
            source=folder/'source.mp4'
            source.write_bytes(b'TEST original')
            with media_maintenance.lock(folder):
                old = time.time()-3*86400
                for entry in (source,folder/media_maintenance.LOCK_NAME,folder):
                    os.utime(entry,(old,old))
                self.assertEqual(media_reconcile.reconcile(root,'test',purge=True)['temporary'],1)
                self.assertTrue(source.exists())
            self.assertEqual(media_reconcile.reconcile(root,'test')['abandoned'],1)
            self.assertEqual(media_reconcile.reconcile(root,'test',purge=True)['temporaryPurged'],1)
            self.assertFalse(folder.exists())

    def test_linked_lock_is_rejected_before_any_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protected = root/'external'
            protected.touch()
            os.link(protected, root/'.media-maintenance.lock')
            with self.assertRaises(ValueError), media_maintenance.lock(root):
                self.fail('Unexpected lock acquisition')
            self.assertEqual(protected.read_bytes(), b'')
