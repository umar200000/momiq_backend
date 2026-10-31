from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime,timedelta

import backup_bundle
import encrypted_backup
import seed_scenarios


@unittest.skipUnless(shutil.which('age') and shutil.which('age-keygen'), 'age recovery tools required')
class EncryptedBackupTests(unittest.TestCase):
    def test_sealed_snapshot_recovery_and_rejections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data,bundle = root/'data',root/'bundle'
            seed_scenarios.build(data)
            backup_bundle.create(data,bundle)
            identity, wrong = root/'key',root/'other'
            for path in (identity,wrong):
                subprocess.run(['age-keygen','-o',str(path)],capture_output=True,check=True)
            recipient = subprocess.check_output(['age-keygen','-y',str(identity)],text=True).strip()
            sealed = root/'test.age'
            evidence = encrypted_backup.seal(bundle,sealed,recipient)
            self.assertEqual(evidence['sha256'],backup_bundle.digest(sealed))
            created = datetime.fromisoformat(evidence['createdAt'])
            def inspect(now,minimum=1):
                return encrypted_backup.inspect_copy(sealed,evidence,max_age_hours=2,min_bytes=minimum,
                                                      max_bytes=8*1024**3,now=now)
            self.assertTrue(inspect(created+timedelta(hours=2))['ok'])
            for instant in [created-timedelta(seconds=1),created+timedelta(hours=2,seconds=1),
                            datetime.fromisoformat(evidence['expiresAt'])]:
                with self.assertRaises(ValueError):
                    inspect(instant)
            with self.assertRaises(ValueError):
                inspect(created,evidence['bytes']+1)
            before = sealed.read_bytes()
            self.assertNotIn(b'SQLite format 3',before)
            with self.assertRaises(ValueError):
                encrypted_backup.seal(bundle,sealed,recipient)
            self.assertEqual(before,sealed.read_bytes())
            def drill(key=identity,mode='test',digest=evidence['sha256']):
                return encrypted_backup.drill(sealed,key,digest,mode)
            self.assertTrue(drill()['reconciled'])
            for key,mode,digest in [(wrong,'test',evidence['sha256']),
                                    (identity,'production',evidence['sha256']),
                                    (identity,'test','0'*64)]:
                with self.assertRaises(ValueError):
                    drill(key,mode,digest)
            sealed.write_bytes(before[:-1]+bytes([before[-1]^1]))
            with self.assertRaises(ValueError):
                drill(digest=backup_bundle.digest(sealed))
