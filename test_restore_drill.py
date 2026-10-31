from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import backup_bundle
import restore_drill
import server
import wallet


class RestoreDrillTests(unittest.TestCase):
    def test_offline_copy_checks_environment_and_wallet_reconciliation(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(server, 'DATA', root/'data'), patch.object(server, 'ENVIRONMENT', 'test'):
                server.setup()
                with server.db() as con:
                    con.execute("INSERT INTO users VALUES('owner','998000000011','{}',0,'TEST')")
                    wallet.post_entry(con, 'owner', 1000, 'topup', 'TEST-credit', 'operator', 'TEST')
                backup_bundle.create(server.DATA, root/'bundle')
                before = backup_bundle.digest(root/'bundle'/'momiq.sqlite3')
                result = restore_drill.rehearse(root/'bundle', 'test')
                self.assertTrue(result['reconciled'])
                self.assertGreaterEqual(result['journalEntries'], 1)
                with self.assertRaisesRegex(ValueError, 'environment'):
                    restore_drill.rehearse(root/'bundle', 'production')
                self.assertEqual(before, backup_bundle.digest(root/'bundle'/'momiq.sqlite3'))
                with server.db() as con:
                    con.execute("UPDATE wallet_accounts SET balance_minor=901 WHERE user_id='owner'")
                backup_bundle.create(server.DATA, root/'mismatch')
                with self.assertRaisesRegex(ValueError, 'journal mismatch'):
                    restore_drill.rehearse(root/'mismatch', 'test')
