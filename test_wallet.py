import sqlite3
import unittest
from contextlib import closing
import migrations
import wallet


class WalletLedgerTests(unittest.TestCase):
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
