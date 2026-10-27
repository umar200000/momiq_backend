import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from server import ClosingConnection
from unittest.mock import patch
from seed_test_data import seed, fixture_id


class SeedTests(unittest.TestCase):
    def test_seed_is_repeatable_and_clean_preserves_unowned_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'fixtures'
            seed(target)
            with sqlite3.connect(target / 'momiq.sqlite3', factory=ClosingConnection) as con:
                con.execute("UPDATE users SET account=? WHERE id=?", (json.dumps({'profile': {'first': 'Edited'}}), fixture_id('customer')))
                con.execute("INSERT INTO users VALUES('unowned','998000000009','{}',0,'now')")
            seed(target)
            with sqlite3.connect(target / 'momiq.sqlite3', factory=ClosingConnection) as con:
                self.assertEqual(con.execute('SELECT COUNT(*) FROM users').fetchone()[0], 5)
                self.assertIn('Edited', con.execute('SELECT account FROM users WHERE id=?', (fixture_id('customer'),)).fetchone()[0])
            seed(target, clean=True)
            seed(target, clean=True)
            with sqlite3.connect(target / 'momiq.sqlite3', factory=ClosingConnection) as con:
                self.assertEqual(con.execute('SELECT id FROM users').fetchall(), [('unowned',)])

    def test_cannot_seed_live_or_unmarked_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / 'real.txt').write_text('Keep me')
            with self.assertRaises(ValueError): seed(target)
            with self.assertRaises(ValueError): seed(target, clean=True)
            with self.assertRaises(ValueError): seed(target / 'new', mode='production')
            with patch.dict('os.environ', {'MOMIQ_ENV': 'production'}):
                with self.assertRaises(ValueError): seed(target / 'other')
            self.assertEqual((target / 'real.txt').read_text(), 'Keep me')
            self.assertFalse((target / 'new').exists())

    def test_cleanup_refuses_unowned_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'fixtures'
            seed(target)
            with sqlite3.connect(target / 'momiq.sqlite3', factory=ClosingConnection) as con:
                con.execute('INSERT INTO users VALUES(?,?,?,0,?)', ('other','998000000009',
                    json.dumps({'favorites': [fixture_id('boarding')]}), 'now'))
            with self.assertRaisesRegex(ValueError, 'Unowned'): seed(target, clean=True)
            with sqlite3.connect(target / 'momiq.sqlite3', factory=ClosingConnection) as con:
                self.assertEqual(con.execute('SELECT COUNT(*) FROM users').fetchone()[0], 5)
