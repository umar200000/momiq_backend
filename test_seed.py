import json
import base64
import struct
import zlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from server import ClosingConnection
from unittest.mock import patch
from seed_test_data import seed, fixture_id


class SeedTests(unittest.TestCase):
    def test_cleanup_preserves_financial_audit(self):
        import wallet
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'fixtures'
            seed(target)
            with sqlite3.connect(target/'momiq.sqlite3',factory=ClosingConnection) as con:
                con.row_factory=sqlite3.Row
                con.execute('BEGIN IMMEDIATE')
                wallet.post_entry(con,fixture_id('boarding'),100,'topup','test-only','test','synthetic')
            with self.assertRaisesRegex(ValueError,'financial history'): seed(target,clean=True)
            with sqlite3.connect(target/'momiq.sqlite3',factory=ClosingConnection) as con:
                self.assertEqual(con.execute('SELECT COUNT(*) FROM users').fetchone()[0],4)
                self.assertEqual(con.execute('SELECT COUNT(*) FROM wallet_entries').fetchone()[0],1)

    def test_fixture_images_have_valid_png_checksums(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'fixtures'
            seed(target)
            with sqlite3.connect(target / 'momiq.sqlite3', factory=ClosingConnection) as con:
                for (account,) in con.execute('SELECT account FROM users'):
                    raw = base64.b64decode(json.loads(account)['pets'][0]['photo'])
                    offset = 8
                    while offset < len(raw):
                        length = struct.unpack('>I', raw[offset:offset+4])[0]
                        chunk = raw[offset+4:offset+8+length]
                        crc = struct.unpack('>I', raw[offset+8+length:offset+12+length])[0]
                        self.assertEqual(zlib.crc32(chunk), crc)
                        offset += length + 12

    def test_seed_is_repeatable_and_clean_preserves_unowned_records(self):
        import notifications
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'fixtures'
            seed(target)
            with sqlite3.connect(target / 'momiq.sqlite3', factory=ClosingConnection) as con:
                con.execute("UPDATE users SET account=? WHERE id=?", (json.dumps({'profile': {'first': 'Edited'}}), fixture_id('customer')))
                con.execute("INSERT INTO users VALUES('unowned','998000000009','{}',0,'now')")
                con.row_factory=sqlite3.Row
                notifications.publish(con,fixture_id('customer'),'fixture-notice','listing','boarding','rejected','TEST')
                notifications.publish(con,'unowned','keep-notice','listing','boarding','rejected','Keep')
            seed(target)
            with sqlite3.connect(target / 'momiq.sqlite3', factory=ClosingConnection) as con:
                self.assertEqual(con.execute('SELECT COUNT(*) FROM users').fetchone()[0], 5)
                self.assertIn('Edited', con.execute('SELECT account FROM users WHERE id=?', (fixture_id('customer'),)).fetchone()[0])
            seed(target, clean=True)
            seed(target, clean=True)
            with sqlite3.connect(target / 'momiq.sqlite3', factory=ClosingConnection) as con:
                self.assertEqual(con.execute('SELECT id FROM users').fetchall(), [('unowned',)])
                self.assertEqual(con.execute('SELECT user_id FROM notifications').fetchall(), [('unowned',)])

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

    def test_cleanup_preserves_new_conversation_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'fixtures'
            seed(target)
            with sqlite3.connect(target / 'momiq.sqlite3', factory=ClosingConnection) as con:
                con.execute('INSERT INTO conversations(id,customer_id,sitter_id,service,customer_name,sitter_name,created) VALUES(?,?,?,?,?,?,?)',
                            ('test-chat', fixture_id('customer'), fixture_id('boarding'), 'boarding', 'TEST', 'TEST', 'now'))
            with self.assertRaisesRegex(ValueError, 'conversation history'):
                seed(target, clean=True)
            with sqlite3.connect(target / 'momiq.sqlite3', factory=ClosingConnection) as con:
                self.assertEqual(con.execute('SELECT COUNT(*) FROM conversations').fetchone()[0], 1)
                self.assertEqual(con.execute('SELECT COUNT(*) FROM users').fetchone()[0], 4)

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
                con.execute("UPDATE users SET account=? WHERE id='other'",(json.dumps({'favorites':[fixture_id('boarding')+':boarding']}),))
            with self.assertRaisesRegex(ValueError, 'Unowned'): seed(target, clean=True)
