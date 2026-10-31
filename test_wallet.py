import sqlite3
import unittest
from contextlib import closing
from types import SimpleNamespace
import migrations
import wallet


class WalletLedgerTests(unittest.TestCase):
    def test_payment_timestamp_requires_explicit_zone_and_real_past_time(self):
        self.assertIsNone(wallet.payment_time(None))
        self.assertEqual(wallet.payment_time('2026-01-01T15:00:00+05:00'), '2026-01-01T10:00:00+00:00')
        for value in (123, 'yesterday', '2026-01-01T15:00:00', '2099-01-01T00:00:00Z', '1900-01-01T00:00:00Z'):
            with self.assertRaises(ValueError): wallet.payment_time(value)

    def test_history_cursor_reaches_all_records_and_is_owner_scoped(self):
        with closing(sqlite3.connect(':memory:')) as con:
            con.row_factory=sqlite3.Row
            con.execute('CREATE TABLE users(id TEXT PRIMARY KEY)')
            con.executemany('INSERT INTO users VALUES(?)',[('a',),('b',)])
            con.commit();migrations.migrate(con)
            for i in range(45):
                con.execute('INSERT INTO topup_requests(id,user_id,amount_minor,receipt,receipt_hash,qr_version,terms_version,request_id,status,created) VALUES(?,?,?,?,?,?,?,?,?,?)',
                            (f'{i:032x}','a',100,'image',str(i),1,wallet.TERMS_VERSION,str(i),'pending','2026-10-27T00:00:00+00:00'))
            collected=[];cursor=None
            for _ in range(3):
                page=wallet.topup_page(SimpleNamespace(path='/api/wallet/topups'+('?cursor='+cursor if cursor else '')),con,'a')
                collected.extend(r['id'] for r in page['topups']);cursor=page['nextCursor']
            self.assertIsNone(cursor)
            self.assertEqual(len(set(collected)),45)
            with self.assertRaises(wallet.WalletError):
                wallet.topup_page(SimpleNamespace(path='/api/wallet/topups?cursor='+collected[0]),con,'b')

    def test_debit_idempotency_rollback_and_immutable_history(self):
        with closing(sqlite3.connect(':memory:')) as con:
            con.row_factory = sqlite3.Row
            con.execute('PRAGMA foreign_keys=ON')
            con.execute('CREATE TABLE users(id TEXT PRIMARY KEY)')
            con.execute("INSERT INTO users VALUES('sitter')")
            con.commit()
            migrations.migrate(con)
            with self.assertRaises(RuntimeError):
                wallet.post_entry(con, 'sitter', 1, 'topup', 'a', 'admin', 'test')
            con.execute('BEGIN IMMEDIATE')
            entry = wallet.post_entry(con, 'sitter', 1500000, 'topup', 'a', 'admin', 'test')
            self.assertEqual(wallet.post_entry(con, 'sitter', 1500000, 'topup', 'a', 'admin', 'retry'), entry)
            con.commit()
            con.execute('BEGIN IMMEDIATE')
            with self.assertRaises(wallet.WalletError):
                wallet.post_entry(con, 'sitter', -1500001, 'commission', 'b', 'system', 'insufficient')
            con.rollback()
            self.assertEqual(wallet.balance(con, 'sitter'), 1500000)
            con.execute('BEGIN IMMEDIATE')
            wallet.post_entry(con, 'sitter', -1500000, 'commission', 'b', 'system', 'test')
            con.rollback()  # crash/failing business transaction cannot leave a debit
            self.assertEqual(wallet.balance(con, 'sitter'), 1500000)
            con.execute('BEGIN IMMEDIATE')
            wallet.post_entry(con, 'sitter', -1500000, 'commission', 'b', 'system', 'test')
            con.commit()
            self.assertEqual(wallet.balance(con, 'sitter'), 0)
            con.execute('BEGIN IMMEDIATE')
            with self.assertRaises(wallet.WalletError):
                wallet.post_entry(con, 'sitter', 1500001, 'topup', 'a', 'admin', 'changed retry')
            con.rollback()
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute('DELETE FROM wallet_entries')
            con.rollback()
            self.assertEqual(con.execute('SELECT SUM(amount_minor) FROM wallet_entries').fetchone()[0], wallet.balance(con, 'sitter'))


if __name__ == '__main__':
    unittest.main()
