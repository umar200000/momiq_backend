from contextlib import closing,redirect_stderr,redirect_stdout
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
