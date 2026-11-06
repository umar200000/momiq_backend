"""Actual process exits against disposable databases, with durable replay checks."""
from datetime import datetime, timedelta
from itertools import product
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import booking_worker
import notifications
import server
import test_booking_care as fixtures


def crash_child(phase, instant):
    # The caller provides a backup of an isolated fixture, never a live server.
    if server.ENVIRONMENT != 'local':
        raise RuntimeError('Local fixture required')
    original_exit = server.ClosingConnection.__exit__
    original_publish = notifications.publish

    def exit_transaction(con, *args):
        changed = args[0] is None and con.in_transaction and con.total_changes > 0
        if changed and phase == 'before-commit':
            os._exit(79)
        result = original_exit(con, *args)
        if changed and phase == 'after-commit':
            os._exit(79)
        return result

    def publish(*args):
        original_publish(*args)
        if phase == 'first-notice':
            os._exit(79)

    with patch.object(server.ClosingConnection, '__exit__', exit_transaction), \
            patch.object(notifications, 'publish', publish):
        booking_worker.run_once(server.db, 'local', now=datetime.fromisoformat(instant))
    raise AssertionError('Crash boundary was not reached')


class BackgroundRecoveryTests(unittest.TestCase):
    setUp = fixtures.BookingCareTests.setUp
    save = fixtures.BookingCareTests.save
    review = fixtures.BookingCareTests.review
    quote = fixtures.BookingCareTests.quote
    request = fixtures.BookingCareTests.request
    act = fixtures.BookingCareTests.act
    accepted = fixtures.BookingCareTests.accepted
    active = fixtures.BookingCareTests.active

    def snapshot(self):
        with server.db() as con:
            return {table: [tuple(row) for row in con.execute(f'SELECT * FROM {table} ORDER BY rowid')]
                    for table in ('bookings', 'booking_events', 'notifications', 'video_checks',
                                  'video_schedules', 'wallet_accounts', 'wallet_entries', 'audit',
                                  'booking_incidents')}

    def verify_recovery(self, instant, status, prefix, notice_status):
        before = self.snapshot()
        source = server.DATA
        for journal, phase in product(('delete', 'wal'), ('first-notice', 'before-commit', 'after-commit')):
            with self.subTest(journal=journal, phase=phase), TemporaryDirectory(prefix='momiq-background-test-') as tmp:
                target = Path(tmp)
                with server.db() as original:
                    backup = sqlite3.connect(target / 'momiq.sqlite3')
                    try:
                        original.backup(backup)
                        self.assertEqual(backup.execute('PRAGMA journal_mode='+journal).fetchone()[0], journal)
                    finally:
                        backup.close()
                env = {key: value for key, value in os.environ.items() if not key.startswith('MOMIQ_')}
                env.update(MOMIQ_ENV='local', MOMIQ_DATA_DIR=str(target), MOMIQ_ALLOW_TEST_LOGIN='0')
                child = subprocess.run([sys.executable, str(Path(__file__).resolve()), phase, instant.isoformat()],
                                       env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(child.returncode, 79, child.stderr)
                with patch.object(server, 'DATA', target):
                    interrupted = self.snapshot()
                    if phase != 'after-commit':
                        self.assertEqual(interrupted, before)
                    booking_worker.run_once(server.db, 'local', now=instant)
                    restored = self.snapshot()
                    self.assertEqual(booking_worker.run_once(server.db, 'local', now=instant), 0)
                    self.assertEqual(self.snapshot(), restored)
                    if phase == 'after-commit':
                        self.assertEqual(restored, interrupted)
                    for table in ('wallet_accounts', 'wallet_entries', 'booking_incidents'):
                        self.assertEqual(restored[table], before[table], table)
                    self.assertEqual(len(restored['notifications']), len(before['notifications'])+2)
                    for table in ('booking_events', 'audit'):
                        self.assertEqual(len(restored[table]), len(before[table])+(status == 'expired'), table)
                    with server.db() as con:
                        self.assertEqual(con.execute('SELECT status FROM bookings').fetchone()[0], status)
                        notices = con.execute("SELECT user_id,payload FROM notifications WHERE source_key LIKE ? AND json_extract(payload,'$.status')=?",
                                              (prefix+'%', notice_status)).fetchall()
                        self.assertEqual(sorted(row['user_id'] for row in notices), ['abc', 'customer'])
                        self.assertTrue(all(json.loads(row['payload'])['status'] == notice_status for row in notices))
                        self.assertEqual(con.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                        self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.assertEqual(server.DATA, source)
        self.assertEqual(self.snapshot(), before)

    def test_expiry_survives_process_death_without_charging_or_repeating(self):
        self.request()
        self.verify_recovery(self.now+timedelta(hours=2), 'expired', 'booking:', 'expired')

    def test_no_show_reminder_survives_process_death_without_a_finding(self):
        self.accepted()
        self.verify_recovery(self.start+timedelta(minutes=30), 'accepted', 'booking-reminder:', 'complaint_available')

    def test_missing_video_survives_process_death_without_penalty(self):
        self.active()
        self.verify_recovery(self.start+timedelta(hours=5), 'active', 'video-followup:', 'video_missing')


if __name__ == '__main__':
    crash_child(*sys.argv[1:])
