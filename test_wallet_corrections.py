import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import migrations
import wallet
import wallet_corrections as corrections


class CorrectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'test.sqlite3'
        self.con=self.connect();self.addCleanup(self.con.close)
        self.con.execute('CREATE TABLE users(id TEXT PRIMARY KEY)')
        self.con.execute('CREATE TABLE audit(id INTEGER PRIMARY KEY,actor TEXT,action TEXT,target TEXT,time TEXT)')
        self.con.execute("INSERT INTO users VALUES('sitter')");self.con.commit()
        migrations.migrate(self.con)
        self.topup='a'*32
        self.con.execute("INSERT INTO topup_requests(id,user_id,amount_minor,receipt,receipt_hash,qr_version,terms_version,request_id,status,created,transfer_reference) VALUES(?,'sitter',1000,'synthetic','hash',1,'v1','fixture','approved','2026-10-29','TEST-XOLIS')",(self.topup,))
        self.original=wallet.post_entry(self.con,'sitter',1000,'topup','topup:'+self.topup,'first-admin','TEST mistaken credit')
        self.con.commit()

    def connect(self):
        con=sqlite3.connect(self.path,timeout=10);con.row_factory=sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON');return con

    def payload(self, **changes):
        return dict({'requestId':'test-once','amountMinor':400,'expectedCorrectedMinor':0,'reason':'TEST duplicate amount'},**changes)

    def apply(self,data=None,actor='operator',topup=None,con=None):
        con=con or self.con
        with con:
            con.execute('BEGIN IMMEDIATE')
            return corrections.correct(con,actor,topup or self.topup,data or self.payload())

    def test_source_link_exact_retry_and_immutable_evidence(self):
        original=dict(self.con.execute('SELECT * FROM wallet_entries WHERE id=?',(self.original,)).fetchone())
        result=self.apply();self.assertEqual(self.apply(),result)
        self.assertEqual(result['originalEntryId'],self.original)
        self.assertEqual(wallet.balance(self.con,'sitter'),600)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM notifications').fetchone()[0],1)
        self.assertEqual(self.con.execute('SELECT actor FROM audit').fetchone()[0],'operator')
        self.assertEqual(dict(self.con.execute('SELECT * FROM wallet_entries WHERE id=?',(self.original,)).fetchone()),original)
        for sql in ('DELETE FROM wallet_corrections',"UPDATE wallet_corrections SET reason='changed'",'DELETE FROM wallet_entries'):
            with self.assertRaises(sqlite3.IntegrityError):
                with self.con:self.con.execute(sql)
        self.assertEqual(self.con.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_changed_retries_stale_admin_and_original_ceiling(self):
        self.apply()
        for data in (self.payload(reason='different'),self.payload(amountMinor=401),self.payload(requestId='new-admin'),self.payload(requestId='too-much',expectedCorrectedMinor=400,amountMinor=601)):
            with self.assertRaises(wallet.WalletError):self.apply(data)
        with self.assertRaises(wallet.WalletError):self.apply(actor='other-admin')
        self.apply(self.payload(requestId='remainder',expectedCorrectedMinor=400,amountMinor=600))
        self.assertEqual(wallet.balance(self.con,'sitter'),0)
        # Replenishing funds never permits correcting more than the original credit.
        with self.con:
            self.con.execute('BEGIN IMMEDIATE');wallet.post_entry(self.con,'sitter',100,'topup','later','admin','TEST')
        with self.assertRaises(wallet.WalletError):self.apply(self.payload(requestId='over',expectedCorrectedMinor=1000,amountMinor=1))
        self.assertEqual(wallet.balance(self.con,'sitter'),100)

    def test_insufficient_balance_and_invalid_payload_leave_no_debt_or_records(self):
        with self.con:
            self.con.execute('BEGIN IMMEDIATE');wallet.post_entry(self.con,'sitter',-601,'commission','spent','system','TEST spent')
        with self.assertRaisesRegex(wallet.WalletError,'Balans yetarli'):self.apply()
        for changes in ({'amountMinor':True},{'amountMinor':1.2},{'amountMinor':0},{'amountMinor':-1},{'expectedCorrectedMinor':False},{'reason':' '},{'requestId':''},{'extra':'bad'}):
            with self.assertRaises(ValueError):self.apply(self.payload(**changes))
        self.assertEqual(wallet.balance(self.con,'sitter'),399)
        self.assertEqual(corrections.total(self.con,self.topup),0)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM audit').fetchone()[0],0)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM notifications').fetchone()[0],0)

    def test_notice_failure_rolls_back_every_financial_change(self):
        with patch.object(corrections.notifications,'publish',side_effect=RuntimeError('TEST failure')):
            with self.assertRaises(RuntimeError):self.apply()
        self.assertEqual(wallet.balance(self.con,'sitter'),1000)
        self.assertEqual(corrections.total(self.con,self.topup),0)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM wallet_entries').fetchone()[0],1)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM audit').fetchone()[0],0)

    def test_two_operators_or_identical_retry_never_double_debit(self):
        def run(index, same):
            with closing(self.connect()) as con:
                try:return self.apply(self.payload(requestId='same' if same else 'request-'+str(index)),con=con)['id']
                except wallet.WalletError as e:return e.status
        with ThreadPoolExecutor(2) as pool:result=list(pool.map(lambda i:run(i,False),range(2)))
        self.assertEqual(sum(value==409 for value in result),1)
        self.assertEqual(wallet.balance(self.con,'sitter'),600)
        # Exact retries of the winning committed request are stable, even concurrently.
        request=self.con.execute('SELECT request_id FROM wallet_corrections').fetchone()[0]
        def retry(_):
            with closing(self.connect()) as con:return self.apply(self.payload(requestId=request),con=con)['id']
        with ThreadPoolExecutor(2) as pool:self.assertEqual(len(set(pool.map(retry,range(2)))),1)
        self.assertEqual(wallet.balance(self.con,'sitter'),600)

    def test_unapproved_or_missing_original_credit_is_not_adjustable(self):
        with self.con:self.con.execute("UPDATE topup_requests SET status='pending' WHERE id=?",(self.topup,))
        with self.assertRaises(wallet.WalletError):self.apply()
        with self.assertRaises(wallet.WalletError):self.apply(topup='b'*32)
        self.assertEqual(wallet.balance(self.con,'sitter'),1000)


if __name__=='__main__':unittest.main()
