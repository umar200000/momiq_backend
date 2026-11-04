from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import notifications
import push_sandbox
import seed_scenarios
from seed_test_data import fixture_id, seed


class PushSandboxTests(unittest.TestCase):
    def test_muted_and_blocked_notices_remain_in_history_without_late_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'demo'
            seed_scenarios.build(root)
            uid=fixture_id('personal')
            push_sandbox.replay(root,'personal')
            with closing(sqlite3.connect(root/'momiq.sqlite3')) as con:
                with con:
                    con.execute("UPDATE users SET account=json_set(account,'$.notifications',json(?)) WHERE id=?",
                                (json.dumps({'chat':False,'orders':False,'video':False}),uid))
                    for kind,status in [('conversation','message'),('booking','accepted'),('care','video_reminder'),
                                        ('care','video_missing'),('care','video_explanation'),('care','video'),('support','updated')]:
                        notifications.publish(con,uid,'pref-'+kind+status,kind,'test-target',status,'')
                before=list(con.iterdump())
                result=push_sandbox.replay(root,'personal','unavailable')
                self.assertEqual((result['suppressed'],result['accepted'],result['retryPending']),(6,0,True))
                self.assertEqual(push_sandbox.replay(root,'personal')['accepted'],1)
                self.assertEqual(list(con.iterdump()),before)
                with con:
                    con.execute("UPDATE users SET blocked=1 WHERE id=?",(uid,))
                    notifications.publish(con,uid,'blocked-support','support','test-target','updated','')
                result=push_sandbox.replay(root,'personal')
                self.assertEqual((result['suppressed'],result['acknowledged'],result['accepted']),(1,0,0))
                with con:
                    con.execute("UPDATE users SET blocked=0,account=json_set(account,'$.notifications',json('{}')) WHERE id=?",(uid,))
                    notifications.publish(con,uid,'new-chat','conversation','test-target','message','')
                self.assertEqual(push_sandbox.replay(root,'personal')['accepted'],1)
                expected=[str(row[0]) for row in con.execute(
                    "SELECT id FROM notifications WHERE user_id=? AND source_key IN ('pref-supportupdated','new-chat') ORDER BY id",(uid,))]
                with closing(sqlite3.connect(root/'push-sandbox.sqlite3')) as provider:
                    delivered=[json.loads(row[0])['noticeId'] for row in provider.execute(
                        'SELECT payload FROM received WHERE owner=? AND notice>=? ORDER BY notice',(uid,int(expected[0])-6))]
                    self.assertEqual(delivered,expected)

    def test_foreign_provider_file_is_preserved_and_an_old_simulator_keeps_its_cursor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'test'
            seed_scenarios.build(root)
            path=root/'push-sandbox.sqlite3'
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE unrelated(value TEXT)')
                db.execute("INSERT INTO unrelated VALUES('preserve')")
            before=path.read_bytes()
            with self.assertRaisesRegex(ValueError,'schema'):push_sandbox.replay(root,'personal')
            self.assertEqual(path.read_bytes(),before)
            path.unlink()
            with closing(sqlite3.connect(path)) as db, db:
                db.executescript("""CREATE TABLE IF NOT EXISTS progress(owner TEXT PRIMARY KEY,acked INTEGER NOT NULL);
                    CREATE TABLE IF NOT EXISTS received(owner TEXT NOT NULL,notice INTEGER NOT NULL,
                    payload TEXT NOT NULL,PRIMARY KEY(owner,notice));""")
                db.execute('INSERT INTO progress VALUES(?,?)',(fixture_id('personal'),19))
            self.assertEqual(push_sandbox.replay(root,'personal')['acknowledged'],0)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT acked FROM progress').fetchone(),(19,))
                self.assertNotEqual(db.execute('PRAGMA application_id').fetchone(),(0,))

    def test_manual_test_receipts_and_finance_push_without_a_payment_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'demo'
            self.assertEqual(seed_scenarios.build(root,payments=True),'created')
            self.assertEqual(seed_scenarios.build(root,payments=True),'already-created')
            with closing(sqlite3.connect(root/'momiq.sqlite3')) as con:
                self.assertEqual(dict(con.execute('SELECT status,COUNT(*) FROM topup_requests GROUP BY status')),
                                 {'approved':1,'needs_info':1,'pending':2,'rejected':1})
                self.assertEqual(con.execute("SELECT balance_minor FROM wallet_accounts WHERE user_id=?",
                                 (fixture_id('personal'),)).fetchone(),(2000000,))
                self.assertEqual(con.execute("SELECT count(*) FROM wallet_entries WHERE user_id=? AND kind='topup'",
                                 (fixture_id('personal'),)).fetchone(),(1,))
                self.assertEqual(con.execute("SELECT count(*) FROM topup_history WHERE event='resubmitted'").fetchone(),(1,))
            self.assertGreater(push_sandbox.replay(root,'personal')['acknowledged'],0)

    def test_retry_commit_visibility_and_sanitized_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'test'
            seed_scenarios.build(root)
            owner = 'personal'
            uid = fixture_id(owner)
            with closing(sqlite3.connect(root/'momiq.sqlite3')) as writer:
                writer.execute('BEGIN IMMEDIATE')
                notifications.publish(writer,uid,'TEST notice','support','PRIVATE ticket','updated','PRIVATE text')
                self.assertEqual(push_sandbox.replay(root,owner)['accepted'],0)
                writer.rollback()
                self.assertEqual(push_sandbox.replay(root,owner)['accepted'],0)
                writer.execute('BEGIN IMMEDIATE')
                notifications.publish(writer,uid,'TEST notice','support','PRIVATE ticket','updated','PRIVATE text')
                writer.commit()
                before = list(writer.iterdump())
                self.assertTrue(push_sandbox.replay(root,owner,'unavailable')['retryPending'])
                self.assertEqual(push_sandbox.replay(root,owner,'lost-response')['accepted'],1)
                result = push_sandbox.replay(root,owner)
                self.assertEqual((result['accepted'],result['duplicate'],result['acknowledged']), (0,1,1))
                self.assertEqual(push_sandbox.replay(root,owner)['acknowledged'],0)
                with closing(sqlite3.connect(root/'push-sandbox.sqlite3')) as provider:
                    row = provider.execute('SELECT owner,notice,payload FROM received').fetchone()
                    self.assertEqual(row[0], uid)
                    self.assertEqual(json.loads(row[2]),{'noticeId':str(row[1]),'title':'Momiq','body':'Yangi bildirishnoma'})
                self.assertEqual(list(writer.iterdump()),before)

    def test_foreign_instance_and_hosted_runtime_never_start_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'other'
            seed(root,'local')
            with self.assertRaises(ValueError):
                push_sandbox.replay(root,'customer')
            with patch.dict('os.environ',MOMIQ_ENV='production'), self.assertRaises(ValueError):
                push_sandbox.replay(root,'customer')
            self.assertFalse((root/'push-sandbox.sqlite3').exists())
