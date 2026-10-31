import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
import migrations


class MigrationTests(unittest.TestCase):
    def test_admin_revocation_upgrade_removes_only_orphans_and_rename_revokes(self):
        with closing(sqlite3.connect(':memory:')) as con:
            con.execute('CREATE TABLE users(id TEXT PRIMARY KEY)')
            con.execute('CREATE TABLE admins(username TEXT PRIMARY KEY,salt TEXT NOT NULL,hash TEXT NOT NULL)')
            con.execute('CREATE TABLE sessions(hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,role TEXT NOT NULL,expires REAL NOT NULL)')
            con.execute("INSERT INTO admins VALUES('existing','salt','hash')")
            con.executemany('INSERT INTO sessions VALUES(?,?,?,?)',[
                ('keep','existing','admin',9999999999),('orphan','removed','admin',9999999999),
                ('client','existing','client',9999999999)])
            con.commit()
            with patch.object(migrations,'MIGRATIONS',migrations.MIGRATIONS[:22]):migrations.migrate(con)
            self.assertEqual(migrations.migrate(con),[23,24,25,26,27,28])
            self.assertEqual(con.execute('SELECT hash FROM sessions ORDER BY hash').fetchall(),[('client',),('keep',)])
            with con:con.execute("UPDATE admins SET username='renamed' WHERE username='existing'")
            self.assertEqual(con.execute('SELECT hash FROM sessions').fetchall(),[('client',)])
            self.assertEqual(migrations.migrate(con),[])

    def test_existing_audit_survives_and_cannot_be_updated_deleted_or_replaced(self):
        with closing(sqlite3.connect(':memory:')) as con:
            con.execute('CREATE TABLE users(id TEXT PRIMARY KEY)')
            con.execute('CREATE TABLE audit(id INTEGER PRIMARY KEY,actor TEXT,action TEXT,target TEXT,time TEXT)')
            con.execute("INSERT INTO audit VALUES(7,'old-operator','TEST-review','TEST-source','2026-10-28')")
            con.commit()
            old=con.execute('SELECT * FROM audit').fetchall()
            original=migrations.MIGRATIONS
            with patch.object(migrations,'MIGRATIONS',original[:21]):migrations.migrate(con)
            self.assertEqual(migrations.migrate(con),[22,23,24,25,26,27,28])
            self.assertEqual(con.execute('SELECT * FROM audit').fetchall(),old)
            for sql in ("UPDATE audit SET actor='forged' WHERE id=7",'DELETE FROM audit WHERE id=7',"INSERT OR REPLACE INTO audit VALUES(7,'forged','TEST','TEST','TEST')"):
                with self.assertRaises(sqlite3.IntegrityError):
                    with con:con.execute(sql)
                self.assertEqual(con.execute('SELECT * FROM audit').fetchall(),old)
            with con:con.execute("INSERT INTO audit(actor,action,target,time) VALUES('operator','TEST-next','TEST-source','2026-10-29')")
            self.assertEqual(con.execute('SELECT COUNT(*) FROM audit').fetchone()[0],2)
            self.assertEqual(migrations.migrate(con),[])

    def test_old_qr_evidence_survives_but_new_payments_require_activation(self):
        import wallet
        with closing(sqlite3.connect(':memory:')) as con:
            con.row_factory=sqlite3.Row
            con.execute('CREATE TABLE users(id TEXT PRIMARY KEY)')
            original=migrations.MIGRATIONS
            with patch.object(migrations,'MIGRATIONS',original[:3]): migrations.migrate(con)
            con.execute("UPDATE platform_settings SET qr_image='legacy-test-image'")
            con.commit();migrations.migrate(con)
            self.assertFalse(wallet.settings(con)['qrActive'])
            row=con.execute('SELECT * FROM platform_settings').fetchone()
            self.assertEqual(row['qr_image'],'legacy-test-image')
            self.assertEqual(row['legacy_receipt_allowed'],1)

    def test_existing_payment_requests_keep_their_evidence(self):
        with closing(sqlite3.connect(':memory:')) as con:
            con.execute('PRAGMA foreign_keys=ON')
            con.execute('CREATE TABLE users(id TEXT PRIMARY KEY)')
            con.execute("INSERT INTO users VALUES('sitter')")
            con.commit()
            original=migrations.MIGRATIONS
            with patch.object(migrations,'MIGRATIONS',original[:4]): migrations.migrate(con)
            con.execute("INSERT INTO topup_requests(id,user_id,amount_minor,receipt,receipt_hash,qr_version,terms_version,request_id,status,created) VALUES('old','sitter',1500000,'receipt','hash',1,'v1','once','pending','2026-01-01')")
            con.commit();self.assertEqual(migrations.migrate(con),[5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28])
            self.assertEqual(con.execute('SELECT receipt,amount_minor,payer_reference,paid_at FROM topup_requests').fetchone(),('receipt',1500000,'',None))
            self.assertEqual(con.execute('SELECT receipt FROM topup_evidence_claims').fetchone()[0],'receipt')
            self.assertEqual(con.execute('SELECT event FROM topup_history').fetchone()[0],'migrated')
            self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_legacy_data_preserved_and_idempotent(self):
        with closing(sqlite3.connect(':memory:')) as con:
            con.execute('CREATE TABLE users(id TEXT PRIMARY KEY, account TEXT)')
            con.execute("INSERT INTO users VALUES('real', '{\"profile\":{}}')")
            con.commit()
            self.assertEqual(migrations.migrate(con), [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28])
            self.assertEqual(migrations.migrate(con), [])
            self.assertEqual(con.execute('SELECT * FROM users').fetchall(), [('real','{"profile":{}}')])
            self.assertEqual(con.execute('SELECT * FROM account_revisions').fetchall(), [('real',0)])

    def test_failed_upgrade_rolls_back_schema_and_history(self):
        with closing(sqlite3.connect(':memory:')) as con:
            broken = ((1, 'broken', ('CREATE TABLE should_rollback(id INTEGER)', 'INSERT INTO missing VALUES(1)')),)
            with patch.object(migrations, 'MIGRATIONS', broken):
                with self.assertRaises(sqlite3.OperationalError):
                    migrations.migrate(con)
            self.assertEqual(con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [])

    def test_changed_or_unknown_migration_rejected(self):
        with closing(sqlite3.connect(':memory:')) as con:
            con.execute('CREATE TABLE users(id TEXT PRIMARY KEY)')
            migrations.migrate(con)
            con.execute("UPDATE schema_migrations SET checksum='changed'")
            con.commit()
            with self.assertRaisesRegex(RuntimeError, 'checksum'):
                migrations.migrate(con)
            con.execute('UPDATE schema_migrations SET version=999 WHERE version=1')
            con.commit()
            with self.assertRaisesRegex(RuntimeError, 'newer'):
                migrations.migrate(con)

    def test_backup_includes_wal_and_dry_run_preserves_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source, backup = (Path(directory)/name for name in ('source.db','backup.db'))
            with closing(sqlite3.connect(source)) as con:
                con.execute('PRAGMA journal_mode=WAL')
                con.execute('CREATE TABLE users(id TEXT PRIMARY KEY)')
                con.execute("INSERT INTO users VALUES('persist')")
                con.commit()
                migrations.backup_database(source, backup)
                with closing(sqlite3.connect(backup)) as copy:
                    self.assertEqual(migrations.migrate(copy), [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28])
                    self.assertEqual(copy.execute('SELECT user_id FROM account_revisions').fetchone()[0], 'persist')
                self.assertIsNone(con.execute("SELECT name FROM sqlite_master WHERE name='schema_migrations'").fetchone())
                with self.assertRaises(ValueError):
                    migrations.backup_database(source, backup)
