from datetime import datetime,timedelta,timezone
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import offsite_copy


class MountedCopyTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.source=self.root/'synthetic.age'
        self.source.write_bytes(b'age-encryption.org/v1\nTEST transport bytes')
        self.mount=self.root/'ordinary-directory'
        self.mount.mkdir()
        now=datetime.now(timezone.utc)
        self.receipt={'sha256':hashlib.sha256(self.source.read_bytes()).hexdigest(),
                      'bytes':self.source.stat().st_size,'createdAt':now.isoformat(),
                      'expiresAt':(now+timedelta(hours=1)).isoformat()}

    def copy(self):
        return offsite_copy.replicate(self.source,self.receipt,self.mount,max_age_hours=1,max_bytes=1024)

    def test_absent_mount_never_falls_back_to_the_local_disk(self):
        with self.assertRaisesRegex(ValueError,'mounted'):self.copy()
        self.assertEqual(list(self.mount.iterdir()),[])

    def test_interrupted_and_repeated_copies_verify_without_overwriting(self):
        target=self.mount/(self.receipt['sha256']+'.age')
        partial=target.with_suffix('.partial')
        partial.write_bytes(b'Interrupted TEST copy')
        with patch.object(offsite_copy,'destination',return_value=self.mount):
            self.assertFalse(self.copy()['alreadyPresent'])
            self.assertEqual(target.read_bytes(),self.source.read_bytes())
            self.assertFalse(partial.exists())
            self.assertTrue(self.copy()['alreadyPresent'])
            target.write_bytes(b'TEST conflict')
            with self.assertRaises(ValueError):self.copy()
            self.assertEqual(target.read_bytes(),b'TEST conflict')

    def test_source_changes_during_copy_are_not_published(self):
        def changed(*args):
            with self.source.open('ab') as stream:stream.write(b'TEST')
            return self.mount
        with patch.object(offsite_copy,'destination',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'grew'):self.copy()
        self.assertFalse(list(self.mount.glob('*.age')))
        self.assertFalse(list(self.mount.glob('*.partial')))
