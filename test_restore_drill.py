from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import backup_bundle
import restore_drill
import server
import wallet


class RestoreDrillTests(unittest.TestCase):
    def test_preupgrade_backup_migrates_only_its_disposable_restore(self):
        import migrations
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(server,'DATA',root/'source'), patch.object(server,'ENVIRONMENT','test'):
                with patch.object(migrations,'MIGRATIONS',migrations.MIGRATIONS[:-1]):
                    server.setup()
                backup_bundle.create(server.DATA,root/'copy')
                original=backup_bundle.digest(root/'copy'/'momiq.sqlite3')
                result=restore_drill.rehearse(root/'copy','test')
                self.assertEqual(result['migrationsApplied'],[28])
                self.assertEqual(result['schemaBefore'],27)
                self.assertEqual(result['schema'],28)
                self.assertEqual(original,backup_bundle.digest(root/'copy'/'momiq.sqlite3'))
                with server.db() as con:
                    self.assertEqual(con.execute('SELECT max(version) FROM schema_migrations').fetchone()[0],27)
    def test_matching_total_does_not_hide_a_wrong_payment_decision(self):
        from contextlib import closing
        import sqlite3
        import seed_scenarios
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            data=root/'data'
            seed_scenarios.build(data,payments=True)
            with closing(sqlite3.connect(data/'momiq.sqlite3')) as con:
                with con:
                    con.execute("UPDATE topup_requests SET status='rejected' WHERE status='approved'")
            backup_bundle.create(data,root/'copy')
            with self.assertRaisesRegex(ValueError,'decision and credit'):
                restore_drill.rehearse(root/'copy','test')

    def test_orphan_credit_is_refused_even_when_the_final_balance_matches(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(server,'DATA',root/'data'),patch.object(server,'ENVIRONMENT','test'):
                server.setup()
                with server.db() as con:
                    con.execute("INSERT INTO users VALUES('owner','998000000011','{}',0,'TEST')")
                    wallet.post_entry(con,'owner',100,'topup','topup:'+'a'*32,'TEST','TEST')
                backup_bundle.create(server.DATA,root/'copy')
                with self.assertRaisesRegex(ValueError,'decision and credit'):
                    restore_drill.rehearse(root/'copy','test')

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
