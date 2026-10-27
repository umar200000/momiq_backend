import sqlite3
import unittest
from contextlib import closing
import migrations
import notifications


class NotificationTests(unittest.TestCase):
    def test_notice_shares_transaction_and_deduplicates_source(self):
        with closing(sqlite3.connect(':memory:')) as con:
            con.row_factory = sqlite3.Row
            con.execute('CREATE TABLE users(id TEXT PRIMARY KEY)')
            con.execute("INSERT INTO users VALUES('owner')")
            con.commit(); migrations.migrate(con)
            args = (con,'owner','source','wallet_topup','test','approved','TEST')
            with self.assertRaises(RuntimeError): notifications.publish(*args)
            con.execute('BEGIN IMMEDIATE'); notifications.publish(*args); con.rollback()
            self.assertEqual(con.execute('SELECT COUNT(*) FROM notifications').fetchone()[0],0)
            con.execute('BEGIN IMMEDIATE'); notifications.publish(*args); notifications.publish(*args); con.commit()
            self.assertEqual(con.execute('SELECT COUNT(*) FROM notifications').fetchone()[0],1)
            con.execute('BEGIN IMMEDIATE')
            with self.assertRaises(ValueError): notifications.publish(con,'owner','source','wallet_topup','different','approved','TEST')
            con.rollback()
            with self.assertRaises(sqlite3.IntegrityError): con.execute("UPDATE notifications SET payload='tampered'")
