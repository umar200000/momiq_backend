from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import backup_bundle
import migrations
import predeploy_backup
import server


class PredeployBackupTests(unittest.TestCase):
    def test_old_known_schema_is_backed_up_without_migration_or_source_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); data = root / 'runtime'; backups = root / 'backups'
            with patch.object(server, 'DATA', data), patch.object(server, 'ENVIRONMENT', 'test'), \
                    patch.object(migrations, 'MIGRATIONS', migrations.MIGRATIONS[:-1]):
                server.setup()
                with server.db() as con: before = '\n'.join(con.iterdump())
                result = predeploy_backup.create(data, backups, 'a' * 40, 'test')
                self.assertEqual(result['schemaBefore'], 25)
                self.assertEqual(result['verified'], {'database': 'ok', 'mediaFiles': 0})
                target = backups / result['backupName']
                self.assertEqual(backup_bundle.verify(target), result['verified'])
                with server.db() as con: self.assertEqual('\n'.join(con.iterdump()), before)
                with closing(sqlite3.connect(target / 'momiq.sqlite3')) as con:
                    self.assertEqual(con.execute('SELECT max(version) FROM schema_migrations').fetchone()[0], 25)
                self.assertNotIn(str(root), json.dumps(result))
                self.assertLessEqual((backup_bundle.bundle_expiry(target) - datetime.now(timezone.utc)).days, 14)

    def test_invalid_source_environment_history_revision_and_nested_paths_fail_before_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); data = root / 'runtime'; backups = root / 'backups'
            with self.assertRaises(ValueError): predeploy_backup.create(data, backups, 'a' * 40, 'test')
            self.assertFalse(data.exists()); self.assertFalse(backups.exists())
            with patch.object(server, 'DATA', data), patch.object(server, 'ENVIRONMENT', 'test'):
                server.setup()
                for destination, revision, mode in ((data / 'backups', 'a' * 40, 'test'),
                                                     (root, 'a' * 40, 'test'),
                                                     (backups, 'main', 'test'),
                                                     (backups, 'a' * 40, 'production')):
                    with self.assertRaises(ValueError): predeploy_backup.create(data, destination, revision, mode)
                with server.db() as con: con.execute("UPDATE schema_migrations SET checksum='bad' WHERE version=1")
                with self.assertRaises(ValueError): predeploy_backup.create(data, backups, 'a' * 40, 'test')
                with server.db() as con: con.execute('DELETE FROM schema_migrations WHERE version=1')
                with self.assertRaises(ValueError): predeploy_backup.create(data, backups, 'a' * 40, 'test')
            self.assertFalse(backups.exists())

    def test_collision_preserves_existing_backup_and_failed_cli_reveals_no_private_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); data = root / 'private-runtime'; backups = root / 'backups'
            with patch.object(server, 'DATA', data), patch.object(server, 'ENVIRONMENT', 'test'):
                server.setup()
                with patch.object(predeploy_backup, 'datetime') as clock, \
                        patch.object(predeploy_backup.secrets, 'token_hex', return_value='1234abcd'):
                    clock.now.return_value = datetime(2026, 10, 29, tzinfo=timezone.utc)
                    first = predeploy_backup.create(data, backups, 'a' * 40, 'test')
                    target = backups / first['backupName']
                    original = (target / 'manifest.json').read_bytes()
                    with self.assertRaises(ValueError): predeploy_backup.create(data, backups, 'b' * 40, 'test')
                    self.assertEqual((target / 'manifest.json').read_bytes(), original)
                result = subprocess.run([sys.executable, str(Path(predeploy_backup.__file__)),
                    '--data', str(data), '--backup-root', str(backups), '--revision', 'a' * 40,
                    '--mode', 'production'], capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, '')
                self.assertEqual(result.stderr, 'Pre-migration backup failed; migration must not proceed\n')

    def test_copy_failure_is_fatal_and_does_not_return_a_verified_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); data = root / 'runtime'
            with patch.object(server, 'DATA', data), patch.object(server, 'ENVIRONMENT', 'test'):
                server.setup()
                with server.db() as con: before = '\n'.join(con.iterdump())
                with patch.object(backup_bundle, 'create', side_effect=OSError('TEST disk full')):
                    with self.assertRaises(OSError):
                        predeploy_backup.create(data, root / 'backups', 'a' * 40, 'test')
                with server.db() as con: self.assertEqual('\n'.join(con.iterdump()), before)
