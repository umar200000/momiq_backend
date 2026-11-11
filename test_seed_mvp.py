import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import catalog
from seed_mvp import build
from seed_test_data import seed, fixture_id
from server import ClosingConnection
import test_seed


class MvpSeedTests(unittest.TestCase):
    def test_three_visible_services_without_bookings_and_idempotent_after_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'mvp'
            self.assertEqual(build(target), 'created')
            with sqlite3.connect(target / 'momiq.sqlite3', factory=ClosingConnection) as con:
                con.row_factory = sqlite3.Row
                listings = list(catalog.profiles(con, 'local'))
                self.assertEqual(len(listings), 3)
                self.assertTrue(all(item['testOnly'] for item in listings))
                self.assertEqual({item['service'] for item in listings}, {0, 1, 2})
                self.assertEqual(list(catalog.profiles(con, 'production')), [])
                for table in ('bookings', 'booking_quotes', 'topup_requests', 'conversations'):
                    self.assertEqual(con.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0], 0)
                self.assertEqual(con.execute('SELECT COUNT(*) FROM wallet_entries').fetchone()[0], 3)
                self.assertEqual(con.execute('SELECT SUM(amount_minor) FROM wallet_entries').fetchone()[0], 300000000)
                self.assertEqual(con.execute('SELECT SUM(balance_minor) FROM wallet_accounts').fetchone()[0], 300000000)
                con.execute('UPDATE users SET blocked=1 WHERE id=?', (fixture_id('boarding'),))
            before = test_seed.SeedTests().snapshot(target)
            self.assertEqual(build(target), 'already-created')
            self.assertEqual(test_seed.SeedTests().snapshot(target), before)

    def test_refuses_existing_hosted_or_linked_and_publishes_no_partial_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / 'existing'
            seed(existing)
            before = test_seed.SeedTests().snapshot(existing)
            with self.assertRaisesRegex(ValueError, 'new directory'):
                build(existing)
            self.assertEqual(test_seed.SeedTests().snapshot(existing), before)
            target = Path(tmp) / 'mvp'
            for mode in ('production', 'staging'):
                with patch.dict(os.environ, MOMIQ_ENV=mode), self.assertRaisesRegex(ValueError, 'local/test'):
                    build(target)
            self.assertFalse(target.exists())
            with patch('seed_mvp.populate', side_effect=RuntimeError('TEST interrupted')):
                with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                    build(target)
            self.assertFalse(target.exists())
            build(target)
            link = Path(tmp) / 'linked'
            os.link(target / 'momiq.sqlite3', link)
            original = link.read_bytes()
            with self.assertRaisesRegex(ValueError, 'fixture file'):
                build(target)
            self.assertEqual(link.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
