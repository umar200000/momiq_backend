"""Real process death against isolated TEST databases, never a running server."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

import migrations
import wallet
import wallet_corrections


CHILD = r'''
import os, sqlite3, sys
import wallet_corrections
con = sqlite3.connect(sys.argv[1])
con.row_factory = sqlite3.Row
con.execute('PRAGMA foreign_keys=ON')
con.execute('PRAGMA synchronous=FULL')
phase = sys.argv[2]
if phase == 'after_debit':
    original = wallet_corrections.wallet.post_entry
    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        os._exit(37)
    wallet_corrections.wallet.post_entry = interrupted
con.execute('BEGIN IMMEDIATE')
wallet_corrections.correct(con, 'operator', 'a'*32, {
    'requestId': 'test-once', 'amountMinor': 400,
    'expectedCorrectedMinor': 0, 'reason': 'TEST duplicate amount'})
if phase == 'after_commit':
    con.commit()
os._exit(37)
'''


class CreditReview:
    command = 'POST'
    path = '/api/admin/topups/' + 'b'*32 + '/review'

    def __init__(self, **changes):
        self.payload = dict(decision='approve', revision=0, reason='TEST bank verified',
                            receivedAmountMinor=1000, transferReference='TEST-XOLIS', fundsVerified=True)
        self.payload.update(changes)
        self.response = None

    def body(self):
        return self.payload

    def reply(self, status, response):
        if status != 200:
            raise AssertionError('Unexpected status')
        self.response = response


def interrupt_credit(path, phase):
    class Interrupted(sqlite3.Connection):
        def commit(self):
            if phase == 'before_commit':
                os._exit(37)
            super().commit()
            if phase == 'after_commit':
                os._exit(37)
    con = sqlite3.connect(path, factory=Interrupted)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    con.execute('PRAGMA synchronous=FULL')
    if phase == 'after_credit':
        post = wallet.post_entry
        def interrupt(*args):
            post(*args)
            os._exit(37)
        wallet.post_entry = interrupt
    call = CreditReview()
    wallet.route(call, con, 'operator', call.path, None, 'test')
    raise AssertionError('Expected process interruption')


class WalletProcessRecoveryTests(unittest.TestCase):
    def connect(self, path):
        con = sqlite3.connect(path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        con.execute('PRAGMA synchronous=FULL')
        return con

    def snapshot(self, con):
        names = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {name: sorted((tuple(r) for r in con.execute(
            'SELECT * FROM "' + name.replace('"', '""') + '"')), key=repr)
            for name in names}

    def check_phase(self, journal, phase):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'TEST-process-recovery.sqlite3'
            con = self.connect(path)
            try:
                self.assertEqual(con.execute('PRAGMA journal_mode='+journal).fetchone()[0], journal.lower())
                con.execute('CREATE TABLE users(id TEXT PRIMARY KEY)')
                con.execute('CREATE TABLE audit(id INTEGER PRIMARY KEY,actor TEXT,action TEXT,target TEXT,time TEXT)')
                con.execute("INSERT INTO users VALUES('sitter')")
                con.commit()
                migrations.migrate(con)
                con.execute("INSERT INTO topup_requests(id,user_id,amount_minor,receipt,receipt_hash,qr_version,terms_version,request_id,status,created,transfer_reference) VALUES(?,'sitter',1000,'synthetic','hash',1,'v1','fixture','approved','2026-10-30','TEST-XOLIS')", ('a'*32,))
                wallet.post_entry(con, 'sitter', 1000, 'topup', 'topup:'+'a'*32, 'first-admin', 'TEST mistaken credit')
                con.commit()
                before = self.snapshot(con)
            finally:
                con.close()
            result = subprocess.run(
                [sys.executable, '-c', CHILD, str(path), phase],
                cwd=Path(__file__).resolve().parent, capture_output=True,
                timeout=30, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            self.assertEqual(result.returncode, 37, result.stderr.decode(errors='replace'))
            con = self.connect(path)
            try:
                self.assertEqual(con.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(), [])
                if phase != 'after_commit':
                    self.assertEqual(self.snapshot(con), before)
                else:
                    self.assertEqual(wallet.balance(con, 'sitter'), 600)
                payload = {'requestId': 'test-once', 'amountMinor': 400,
                           'expectedCorrectedMinor': 0, 'reason': 'TEST duplicate amount'}
                def retry(data):
                    with con:
                        con.execute('BEGIN IMMEDIATE')
                        return wallet_corrections.correct(con, 'operator', 'a'*32, data)
                if phase == 'after_commit':
                    committed = self.snapshot(con)
                receipt = retry(payload)
                if phase == 'after_commit':
                    self.assertEqual(self.snapshot(con), committed)
                final = self.snapshot(con)
                self.assertEqual(retry(payload), receipt)
                self.assertEqual(self.snapshot(con), final)
                self.assertEqual(wallet.balance(con, 'sitter'), 600)
                for table, count in [('wallet_entries', 2), ('wallet_corrections', 1), ('audit', 1), ('notifications', 1)]:
                    self.assertEqual(con.execute('SELECT COUNT(*) FROM '+table).fetchone()[0], count)
                for changes in ({'amountMinor': 401}, {'requestId': 'stale-request'}):
                    with self.assertRaises(wallet.WalletError):
                        retry({**payload, **changes})
                    self.assertEqual(self.snapshot(con), final)
            finally:
                con.close()

    def test_credit_approval_recovers_without_duplicating_money_history_or_notice(self):
        for mode in ('DELETE','WAL'):
            for phase in ('after_credit','before_commit','after_commit'):
                with self.subTest(mode=mode,phase=phase), tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp)/'TEST-credit.sqlite3'
                    con = self.connect(path)
                    try:
                        self.assertEqual(con.execute('PRAGMA journal_mode='+mode).fetchone()[0],mode.lower())
                        con.execute('CREATE TABLE users(id TEXT PRIMARY KEY)')
                        con.execute('CREATE TABLE audit(id INTEGER PRIMARY KEY,actor TEXT,action TEXT,target TEXT,time TEXT)')
                        con.execute("INSERT INTO users VALUES('sitter')")
                        con.commit()
                        migrations.migrate(con)
                        con.execute("""INSERT INTO topup_requests
                            (id,user_id,amount_minor,receipt,receipt_hash,qr_version,terms_version,request_id,status,created)
                            VALUES(?,'sitter',1000,'synthetic','TEST-hash',1,'v1','TEST-credit','pending','2026-10-31')""",
                            ('b'*32,))
                        con.commit()
                        before = self.snapshot(con)
                    finally:
                        con.close()
                    run = subprocess.run([sys.executable,'-c',
                        'import sys; from test_wallet_process_recovery import interrupt_credit; interrupt_credit(*sys.argv[1:])',
                        str(path), phase], cwd=Path(__file__).resolve().parent, capture_output=True, timeout=30,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                    self.assertEqual(run.returncode,37,run.stderr.decode(errors='replace'))
                    con = self.connect(path)
                    try:
                        if phase != 'after_commit':
                            self.assertEqual(self.snapshot(con),before)
                        else:
                            self.assertEqual(wallet.balance(con,'sitter'),1000)
                        call = CreditReview()
                        committed = self.snapshot(con)
                        wallet.route(call,con,'operator',call.path,None,'test')
                        self.assertEqual(call.response['topup']['status'],'approved')
                        final = self.snapshot(con)
                        if phase == 'after_commit':
                            self.assertEqual(final,committed)
                        wallet.route(call,con,'operator',call.path,None,'test')
                        self.assertFalse(con.in_transaction)
                        self.assertEqual(wallet.balance(con,'sitter'),1000)
                        for table in ('wallet_entries','topup_history','audit','notifications'):
                            self.assertEqual(len(final[table]),1,table)
                        with self.assertRaises(wallet.WalletError), con:
                            wallet.route(call,con,'different-operator',call.path,None,'test')
                        with self.assertRaises(ValueError), con:
                            wallet.route(CreditReview(decision='reject'),con,'operator',call.path,None,'test')
                        self.assertEqual(self.snapshot(con),final)
                        self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(),[])
                    finally:
                        con.close()

    def test_death_after_debit_rolls_back_every_table(self):
        for journal in ('DELETE', 'WAL'):
            with self.subTest(journal=journal):
                self.check_phase(journal, 'after_debit')

    def test_death_before_commit_rolls_back_ledger_audit_and_notice(self):
        for journal in ('DELETE', 'WAL'):
            with self.subTest(journal=journal):
                self.check_phase(journal, 'before_commit')

    def test_committed_but_lost_response_retry_never_double_debits(self):
        for journal in ('DELETE', 'WAL'):
            with self.subTest(journal=journal):
                self.check_phase(journal, 'after_commit')


if __name__ == '__main__':
    unittest.main()
