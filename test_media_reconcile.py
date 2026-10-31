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
            initial = media_reconcile.reconcile(data, 'test')
            self.assertEqual(initial, dict(orphan=2, temporary=1, recent=1, referenced=0, unsafe=1, purged=0))
            with self.assertRaises(ValueError):
                media_reconcile.reconcile(data, 'production', purge=True)
            self.assertEqual(media_reconcile.reconcile(data, 'test', purge=True, limit=1)['purged'], 1)
            self.assertEqual(media_reconcile.reconcile(data, 'test', purge=True)['purged'], 1)
            self.assertEqual(media_reconcile.reconcile(data, 'test', purge=True)['purged'], 0)
            self.assertTrue((root/f'{2:032x}'/'unknown').is_file())
            self.assertTrue((root/'.upload-active').is_dir())

    def test_linked_lock_is_rejected_before_any_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protected = root/'external'
            protected.touch()
            os.link(protected, root/'.media-maintenance.lock')
            with self.assertRaises(ValueError), media_maintenance.lock(root):
                self.fail('Unexpected lock acquisition')
            self.assertEqual(protected.read_bytes(), b'')
