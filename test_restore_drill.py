from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import backup_bundle
import restore_drill
import server
import wallet


class RestoreDrillTests(unittest.TestCase):
    def test_old_admin_and_client_sessions_are_invalidated_only_on_the_rehearsal_copy(self):
        from contextlib import closing
        import sqlite3
        with TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'data';bundle=root/'backup'
            with patch.object(server,'DATA',source),patch.object(server,'ENVIRONMENT','test'):
                server.setup()
                with server.db() as con:
                    con.execute("INSERT INTO users VALUES('owner','998000000011','{}',0,'TEST')")
                    con.executemany('INSERT INTO sessions VALUES(?,?,?,?)',
                                    [('1'*64,'owner','client',9999999999),('2'*64,'admin','admin',9999999999)])
                backup_bundle.create(source,bundle)
                digest=backup_bundle.digest(bundle/'momiq.sqlite3')
                proof=restore_drill.rehearse(bundle,'test')
                self.assertEqual(proof['restoredSessionsRevoked'],2)
                self.assertEqual(digest,backup_bundle.digest(bundle/'momiq.sqlite3'))
                for folder in (bundle,source):
                    with closing(sqlite3.connect((folder/'momiq.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
                        self.assertEqual(db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0],2)
                        self.assertEqual(db.execute("SELECT COUNT(*) FROM audit WHERE action='recovery-session-reset'").fetchone()[0],0)

    def test_linked_but_excessive_corrections_and_dispute_awards_are_detected(self):
        import sqlite3
        import seed_scenarios
        from contextlib import closing
        with TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'data'
            seed_scenarios.build(source,payments=True)
            with closing(sqlite3.connect(source/'momiq.sqlite3')) as con, con:
                con.row_factory=sqlite3.Row
                con.execute('BEGIN IMMEDIATE')
                approved=con.execute("SELECT * FROM topup_requests WHERE status='approved'").fetchone()
                value=approved['amount_minor']+1
                wallet.post_entry(con,approved['user_id'],value,'topup','TEST-independent-opening','op','TEST')
                debit=wallet.post_entry(con,approved['user_id'],-value,'topup_correction','topup-correction:TEST','op','TEST')
                original=con.execute('SELECT id FROM wallet_entries WHERE source_key=?',('topup:'+approved['id'],)).fetchone()[0]
                con.execute('INSERT INTO wallet_corrections VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                            ('TEST',approved['id'],original,debit,value,0,'TEST-key','op','TEST','TEST',approved['user_id']))
            backup_bundle.create(source,root/'overcorrected')
            with self.assertRaisesRegex(ValueError,'exceeds or skips'):restore_drill.rehearse(root/'overcorrected','test')
            clean=root/'fresh'
            seed_scenarios.build(clean)
            with closing(sqlite3.connect(clean/'momiq.sqlite3')) as con,con:
                con.execute("""INSERT INTO booking_disputes(booking_id,kind,reporter,prior_status,status,revision,
                    created,deadline,resolved_at,outcome,reason,refund_minor)
                    SELECT id,'service',customer_id,'active','resolved',1,created,ends_at,updated,'continue','TEST',1
                    FROM bookings WHERE status='active'""")
                self.assertEqual(con.execute('SELECT COUNT(*) FROM booking_disputes').fetchone()[0],1)
            backup_bundle.create(clean,root/'bad-award')
            with self.assertRaisesRegex(ValueError,'contradicts'):restore_drill.rehearse(root/'bad-award','test')

    def test_recovery_thresholds_use_observed_values_without_rounding_or_assumed_slos(self):
        metrics={'drillSeconds':1.0001,'snapshotAgeSeconds':60}
        self.assertEqual(restore_drill.recovery_status(metrics,None,None),{'breached':[],'limits':{}})
        self.assertEqual(restore_drill.recovery_status(metrics,60,1)['breached'],['drillSeconds'])
        self.assertEqual(restore_drill.recovery_status(metrics,59,2)['breached'],['snapshotAgeSeconds'])
        with self.assertRaises(ValueError):restore_drill.recovery_status(metrics,-1,None)

    def test_balanced_journal_cannot_hide_unearned_booking_refund_or_unlinked_correction(self):
        import seed_scenarios
        import sqlite3
        from contextlib import closing
        for kind,source,value,message in (
                ('commission_refund','booking:'+'f'*32+':refund',10,'booking commission'),
                ('topup_correction','topup-correction:'+'e'*32,-10,'correction and debit')):
            with self.subTest(kind=kind), TemporaryDirectory() as tmp:
                root=Path(tmp)
                seed_scenarios.build(root/'data',payments=True)
                backup_bundle.create(root/'data',root/'before')
                self.assertTrue(restore_drill.rehearse(root/'before','test')['reconciled'])
                with closing(sqlite3.connect(root/'data'/'momiq.sqlite3')) as con, con:
                    con.row_factory=sqlite3.Row
                    owner=con.execute('SELECT user_id FROM wallet_accounts WHERE balance_minor>=10 LIMIT 1').fetchone()[0]
                    con.execute('BEGIN IMMEDIATE')
                    wallet.post_entry(con,owner,value,kind,source,'operator','TEST corrupted link')
                backup_bundle.create(root/'data',root/'after')
                with self.assertRaisesRegex(ValueError,message):
                    restore_drill.rehearse(root/'after','test')

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
