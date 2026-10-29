import io
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults

import deployment_health
import server
from wsgi import application


class DeploymentHealthTests(unittest.TestCase):
    def test_release_identity_is_strict_and_optional_only_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNone(deployment_health.release_sha(root))
            for content in (b'', b'a' * 39, b'A' * 40, b'a' * 40 + b'\nsecret', b'a' * 41):
                (root / '.release-sha').write_bytes(content)
                with self.assertRaises(ValueError):
                    deployment_health.release_sha(root)
            (root / '.release-sha').write_bytes(b'a' * 40 + b'\n')
            self.assertEqual(deployment_health.release_sha(root), 'a' * 40)

    def call(self, path='/api/ready'):
        env = {}; setup_testing_defaults(env)
        env.update(PATH_INFO=path, REQUEST_METHOD='GET', CONTENT_LENGTH='0')
        env['wsgi.input'] = io.BytesIO()
        result = {}
        def start(status, headers):
            result.update(status=int(status.split()[0]), headers=dict(headers))
        result['body'] = json.loads(b''.join(application(env, start)))
        return result

    def test_missing_or_broken_database_is_unready_without_creation_or_details(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(server, 'DATA', Path(tmp)):
            self.assertEqual(self.call('/api/health')['status'], 200)
            self.assertFalse((Path(tmp) / 'momiq.sqlite3').exists())
            result = self.call()
            self.assertEqual((result['status'], result['body']), (503, {'ok': False}))
            self.assertFalse((Path(tmp) / 'momiq.sqlite3').exists())
            (Path(tmp) / 'momiq.sqlite3').write_bytes(b'not-a-database')
            before = (Path(tmp) / 'momiq.sqlite3').read_bytes()
            self.assertEqual(self.call()['status'], 503)
            self.assertEqual((Path(tmp) / 'momiq.sqlite3').read_bytes(), before)

    def test_ready_reads_existing_database_and_rejects_each_incompatibility(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(server, 'DATA', Path(tmp)), \
                patch.object(server, 'ENVIRONMENT', 'test'), patch.object(server, 'RELEASE_SHA', 'a' * 40):
            server.setup()
            with server.db() as con:
                before = '\n'.join(con.iterdump())
                first_migration = tuple(con.execute('SELECT * FROM schema_migrations WHERE version=1').fetchone())
            result = self.call()
            self.assertEqual(result['status'], 200)
            self.assertEqual(result['body'], {'ok': True, 'mode': 'test', 'releaseSha': 'a' * 40,
                                             'schemaVersion': 26})
            self.assertEqual(result['headers']['Cache-Control'], 'no-store')
            with server.db() as con:
                self.assertEqual('\n'.join(con.iterdump()), before)
            with patch.object(server, 'ENVIRONMENT', 'production'):
                self.assertEqual(self.call()['status'], 503)
            with server.db() as con:
                con.execute("UPDATE schema_migrations SET checksum='bad' WHERE version=1")
            self.assertEqual(self.call()['status'], 503)
            with server.db() as con:
                con.execute('DELETE FROM schema_migrations WHERE version=1')
            self.assertEqual(self.call()['status'], 503)
            with server.db() as con:
                con.execute('INSERT INTO schema_migrations VALUES(?,?,?,?)', first_migration)
            self.assertEqual(self.call()['status'], 200)
            # A newer database must never be declared rollback-compatible.
            with server.db() as con:
                con.execute("INSERT INTO schema_migrations VALUES(999,'future','bad','test')")
            self.assertEqual(self.call()['status'], 503)

    def test_declared_schema_is_not_enough_if_an_essential_table_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(server, 'DATA', Path(tmp)):
            server.setup()
            with closing(sqlite3.connect(Path(tmp) / 'momiq.sqlite3')) as con:
                con.execute('DROP TABLE sessions')
                con.commit()
            self.assertEqual(self.call()['status'], 503)
