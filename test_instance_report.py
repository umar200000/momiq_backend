from contextlib import closing,redirect_stderr,redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import seed_scenarios
from tool import instance_report


class InstanceReportTests(unittest.TestCase):
    def test_receipt_bytes_count_current_and_immutable_claims_without_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'demo'
            seed_scenarios.build(root,payments=True)
            with closing(sqlite3.connect(root/'momiq.sqlite3')) as con:
                before=list(con.iterdump())
                current=con.execute('SELECT SUM(length(CAST(receipt AS BLOB))) FROM topup_requests').fetchone()[0]
                claims=con.execute('SELECT SUM(length(CAST(receipt AS BLOB))) FROM topup_evidence_claims').fetchone()[0]
                for limit,expected in ((current+claims,0),(current+claims-1,1)):
                    with redirect_stdout(StringIO()) as output:
                        result=instance_report.main(['--data',str(root),'--mode','test','--max-receipt-stored-base64-bytes',str(limit)])
                    self.assertEqual(result,expected)
                    report=json.loads(output.getvalue())
                    self.assertEqual(report['metrics']['currentReceiptBase64Bytes'],current)
                    self.assertEqual(report['metrics']['evidenceReceiptBase64Bytes'],claims)
                    self.assertEqual(report['metrics']['receiptStoredBase64Bytes'],current+claims)
                    self.assertNotIn(str(root),output.getvalue());self.assertNotIn('TEST',output.getvalue())
                self.assertEqual(list(con.iterdump()),before)

    def test_deadline_queues_report_at_boundary_without_changing_bookings_or_disputes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'demo'
            seed_scenarios.build(root)
            with closing(sqlite3.connect(root/'momiq.sqlite3')) as con:
                due = con.execute("SELECT reply_deadline FROM bookings WHERE status='pending'").fetchone()[0]
                con.execute("""INSERT INTO booking_disputes
                    (booking_id,kind,reporter,prior_status,status,revision,created,deadline)
                    SELECT id,'service',customer_id,status,'open',1,starts_at,? FROM bookings WHERE status='active'""",(due,))
                con.commit()
                original = list(con.iterdump())
                instant = datetime.fromisoformat(due).astimezone(timezone.utc)
                flags = ['--data',str(root),'--mode','test','--max-expired-pending-bookings','0','--max-overdue-open-disputes','0']
                def check(at,expected):
                    with patch.object(instance_report,'datetime',wraps=datetime) as clock, redirect_stdout(StringIO()) as output:
                        clock.now.return_value = at
                        self.assertEqual(instance_report.main(flags),int(bool(expected)))
                    result = json.loads(output.getvalue())
                    self.assertCountEqual(result['breached'],expected)
                    for name in ('expiredPendingBookings','overdueOpenDisputes'):
                        self.assertEqual(result['metrics'][name],int(name in expected))
                check(instant-timedelta(microseconds=1),[])
                check(instant,['expiredPendingBookings','overdueOpenDisputes'])
                self.assertEqual(list(con.iterdump()),original)
                con.execute("UPDATE bookings SET status='expired' WHERE status='pending'")
                con.execute("UPDATE booking_disputes SET status='resolved'")
                con.commit()
                check(instant+timedelta(minutes=1),[])

    def test_bounds_missing_metric_and_owner_scoped_data_stay_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'demo'
            seed_scenarios.build(root,payments=True)
            with closing(sqlite3.connect(root/'momiq.sqlite3')) as con:
                prior=list(con.iterdump())
                for flags,wanted in ((['--max-pending-topups','2'],0),(['--max-pending-topups','1'],1),
                                     (['--min-host-available-ram-bytes','0'],2)):
                    with patch.object(instance_report,'available_ram',return_value=None),redirect_stdout(StringIO()) as output:
                        code=instance_report.main(['--data',str(root),'--mode','test',*flags])
                    self.assertEqual(code,wanted)
                    summary=json.loads(output.getvalue())
                    self.assertEqual(summary['metrics']['pendingTopups'],2)
                    self.assertNotIn(str(root),output.getvalue())
                    self.assertNotIn('TEST',output.getvalue())
                with redirect_stderr(StringIO()) as output:
                    self.assertEqual(instance_report.main(['--data',str(root),'--mode','production']),2)
                self.assertNotIn(str(root),output.getvalue())
                self.assertEqual(prior,list(con.iterdump()))
