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
