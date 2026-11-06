"""Durable retirement and filesystem recovery after real local process exits."""
from datetime import datetime, timedelta
from itertools import product
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import server
import test_booking_care as fixtures
import video_retention

VIDEO = 'a' * 32


def crash_child(phase, instant):
    if server.ENVIRONMENT != 'local':
        raise RuntimeError('Local fixture required')
    original_commit = server.ClosingConnection.commit
    original_unlink = Path.unlink

    def commit(con):
        retired = con.execute('SELECT purged_at FROM video_retirements WHERE video_id=?', (VIDEO,)).fetchone()
        if retired and phase == 'before-retirement' and retired[0] is None:
            os._exit(79)
        original_commit(con)
        if retired and ((phase == 'after-retirement' and retired[0] is None) or
                        (phase == 'after-purge' and retired[0] is not None)):
            os._exit(79)

    def unlink(path, *args, **kwargs):
        result = original_unlink(path, *args, **kwargs)
        if phase == 'after-playback' and path == server.DATA/'care-videos'/VIDEO/'playback.mp4':
            os._exit(79)
        return result

    with patch.object(server.ClosingConnection, 'commit', commit), patch.object(Path, 'unlink', unlink):
        with server.db() as con:
            video_retention.cleanup(con, server.DATA, datetime.fromisoformat(instant))
    raise AssertionError('Crash boundary was not reached')


class RetentionRecoveryTests(unittest.TestCase):
    setUp = fixtures.BookingCareTests.setUp
    save = fixtures.BookingCareTests.save
    review = fixtures.BookingCareTests.review
    quote = fixtures.BookingCareTests.quote
    request = fixtures.BookingCareTests.request
    act = fixtures.BookingCareTests.act
    accepted = fixtures.BookingCareTests.accepted
    active = fixtures.BookingCareTests.active

    def test_retirement_releases_lock_and_retries_partial_deletion_once(self):
        booking = self.active()
        end = self.start+timedelta(hours=2)
        booking = self.act(booking, 'complete', user='customer', now=end)
        self.act(booking, 'complete', now=end)
        expiry = end+timedelta(days=30)
        with server.db() as con:
            con.execute('INSERT INTO booking_videos VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (VIDEO, booking['id'], 'cat-a', self.start.date().isoformat(), 'evening',
                         'abc', 'TEST-retention', 'TEST-fingerprint', 10000, 4, 128, 96,
                         'TEST-video-hash', 'TEST-poster-hash', self.start.isoformat()))
        phases = ('before-retirement', 'after-retirement', 'after-playback', 'after-purge')
        for journal, phase in product(('delete', 'wal'), phases):
            with self.subTest(journal=journal, phase=phase), TemporaryDirectory(prefix='momiq-retention-test-') as tmp:
                root = Path(tmp)
                with server.db() as original:
                    backup = sqlite3.connect(root/'momiq.sqlite3')
                    try:
                        original.backup(backup)
                        self.assertEqual(backup.execute('PRAGMA journal_mode='+journal).fetchone()[0], journal)
                    finally:
                        backup.close()
                folder = root/'care-videos'/VIDEO
                folder.mkdir(parents=True)
                # Cleanup never decodes these synthetic bytes or exposes them via HTTP.
                (folder/'playback.mp4').write_bytes(b'TEST')
                (folder/'poster.jpg').write_bytes(b'TEST')
                unrelated = root/'unrelated.txt'
                unrelated.write_text('TEST preserve')
                env = {key: value for key, value in os.environ.items() if not key.startswith('MOMIQ_')}
                env.update(MOMIQ_ENV='local', MOMIQ_DATA_DIR=str(root), MOMIQ_ALLOW_TEST_LOGIN='0')
                child = subprocess.run([sys.executable, str(Path(__file__).resolve()), phase, expiry.isoformat()],
                                       env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(child.returncode, 79, child.stderr)
                with patch.object(server, 'DATA', root), server.db() as con:
                    row = con.execute('SELECT * FROM booking_videos WHERE id=?', (VIDEO,)).fetchone()
                    self.assertFalse(video_retention.status(con, row, expiry)['available'])
                    self.assertEqual(con.execute('SELECT COUNT(*) FROM video_retirements').fetchone()[0],
                                     0 if phase == 'before-retirement' else 1)
                    if phase == 'after-playback':
                        self.assertFalse((folder/'playback.mp4').exists())
                        self.assertTrue((folder/'poster.jpg').is_file())
                    result = video_retention.cleanup(con, root, expiry)
                    self.assertEqual(result, {'retired': int(phase == 'before-retirement'),
                                              'purged': int(phase != 'after-purge'), 'failed': 0})
                    self.assertEqual(video_retention.cleanup(con, root, expiry),
                                     {'retired': 0, 'purged': 0, 'failed': 0})
                    self.assertFalse(folder.exists())
                    self.assertEqual(unrelated.read_text(), 'TEST preserve')
                    self.assertEqual(con.execute('SELECT COUNT(*) FROM booking_videos').fetchone()[0], 1)
                    for action in ('video-expired', 'video-purged'):
                        self.assertEqual(con.execute('SELECT COUNT(*) FROM audit WHERE action=? AND target=?',
                                                     (action, VIDEO)).fetchone()[0], 1)
                    self.assertIsNotNone(con.execute('SELECT purged_at FROM video_retirements').fetchone()[0])
                    self.assertEqual(con.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                    self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(), [])


if __name__ == '__main__':
    crash_child(*sys.argv[1:])
