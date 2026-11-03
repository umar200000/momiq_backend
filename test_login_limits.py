from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

import server


class LoginLimitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'isolated.sqlite3'
        with self.connect() as con:
            con.execute('CREATE TABLE attempts(key TEXT PRIMARY KEY,count INTEGER,reset REAL)')
            con.execute('PRAGMA journal_mode=WAL')

    def connect(self):
        con = sqlite3.connect(self.path, timeout=5, factory=server.ClosingConnection)
        con.row_factory = sqlite3.Row
        return con

    def attempt(self, key='TEST admin IP'):
        with self.connect() as con:
            try: server.Handler.throttle(None, con, key)
            except server.ApiError as error: return error.status
        return 200

    def test_parallel_requests_share_the_last_available_attempt(self):
        with self.connect() as con:
            con.execute('INSERT INTO attempts VALUES(?,?,?)', ('TEST admin IP', 14, 160))
        barrier = threading.Barrier(4)
        def run(_):
            barrier.wait(timeout=5)
            return self.attempt()
        with patch.object(server.time, 'time', return_value=100), ThreadPoolExecutor(4) as pool:
            results = list(pool.map(run, range(32)))
            self.assertEqual(results.count(200), 1); self.assertEqual(results.count(429), 31)
            self.assertEqual(self.attempt('TEST unrelated IP'), 200)
        with self.connect() as con:
            self.assertEqual(tuple(con.execute('SELECT count,reset FROM attempts WHERE key=?', ('TEST admin IP',)).fetchone()), (15, 160))

    def test_window_boundary_resets_once_and_failed_storage_does_not_consume_attempt(self):
        with self.connect() as con:
            con.execute('INSERT INTO attempts VALUES(?,?,?)', ('TEST admin IP', 15, 100))
        with patch.object(server.time, 'time', return_value=99):
            self.assertEqual(self.attempt(), 429)
        with patch.object(server.time, 'time', return_value=100):
            self.assertEqual(self.attempt(), 200)
            self.assertEqual(self.attempt(), 200)
        with self.connect() as con:
            self.assertEqual(tuple(con.execute('SELECT count,reset FROM attempts').fetchone()), (2, 160))
            con.execute("CREATE TRIGGER fail_attempt BEFORE INSERT ON attempts BEGIN SELECT RAISE(ABORT,'TEST storage failure'); END")
        with patch.object(server.time, 'time', return_value=101), self.assertRaises(sqlite3.IntegrityError):
            self.attempt()
        with self.connect() as con:
            self.assertEqual(tuple(con.execute('SELECT count,reset FROM attempts').fetchone()), (2, 160))
