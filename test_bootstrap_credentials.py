from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import server


class BootstrapCredentialTests(unittest.TestCase):
    def test_hosted_secret_is_validated_and_never_copied_to_a_handoff_file(self):
        with TemporaryDirectory() as tmp,patch.object(server,'DATA',Path(tmp)/'data'),patch.object(server,'ENVIRONMENT','production'):
            with patch.dict(os.environ,{'MOMIQ_ADMIN_PASSWORD':'short'}):
                with self.assertRaisesRegex(ValueError,'operator password'):server.setup()
            with server.db() as con:self.assertIsNone(con.execute('SELECT 1 FROM admins').fetchone())
            value=' TEST supplied bootstrap password '
            with patch.dict(os.environ,{'MOMIQ_ADMIN_PASSWORD':value}):
                server.setup()
            self.assertFalse((server.DATA/'admin-login.txt').exists())
            with server.db() as con:
                salt,digest=con.execute("SELECT salt,hash FROM admins WHERE username='admin'").fetchone()
                self.assertEqual(server.password_hash(value,salt),digest)

    def test_generated_handoff_never_truncates_existing_file_and_restarts_preserve_it(self):
        with TemporaryDirectory() as tmp,patch.object(server,'DATA',Path(tmp)/'data'),patch.dict(os.environ,{'MOMIQ_ADMIN_PASSWORD':''}):
            server.DATA.mkdir()
            external=Path(tmp)/'unrelated'
            external.write_bytes(b'TEST original')
            handoff=server.DATA/'admin-login.txt'
            os.link(external,handoff)
            with self.assertRaises(FileExistsError):server.setup()
            self.assertEqual(external.read_bytes(),b'TEST original')
            with server.db() as con:self.assertIsNone(con.execute('SELECT 1 FROM admins').fetchone())
            handoff.unlink()
            server.setup()
            original=handoff.read_bytes()
            if os.name=='posix':self.assertEqual(handoff.stat().st_mode&0o777,0o600)
            server.setup()
            self.assertEqual(original,handoff.read_bytes())

    def test_concurrent_first_starts_cannot_claim_the_same_database_for_two_environments(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)/'data'
            jobs=[]
            for mode in ('test','production'):
                env={**os.environ,'MOMIQ_ENV':mode,'MOMIQ_ALLOW_TEST_LOGIN':'0','MOMIQ_DATA_DIR':str(root),
                     'MOMIQ_ADMIN_PASSWORD':'TEST initial operator password'}
                env.pop('MOMIQ_AREA_FILE',None);env.pop('MOMIQ_AREA_SHA256',None)
                jobs.append((mode,subprocess.Popen([sys.executable,'-c','import server;server.setup()'],env=env,
                                                   stdout=subprocess.PIPE,stderr=subprocess.PIPE)))
            successful=[]
            for mode,job in jobs:
                _,err=job.communicate(timeout=30)
                if job.returncode==0:successful.append(mode)
                else:self.assertIn(b'belongs to a different environment',err)
            self.assertEqual(len(successful),1)
            with closing(sqlite3.connect(root/'momiq.sqlite3')) as con:
                self.assertEqual(con.execute("SELECT value FROM runtime_metadata WHERE key='environment'").fetchone()[0],successful[0])
                self.assertEqual(con.execute("SELECT COUNT(*) FROM admins").fetchone()[0],1)
