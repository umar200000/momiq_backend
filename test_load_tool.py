"""The load generator must stay isolated and report both workload modes honestly."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parent


class LoadToolTests(unittest.TestCase):
    def test_burst_and_paced_runs_ignore_existing_data_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);existing=root/'existing';existing.mkdir();marker=existing/'momiq.sqlite3';marker.write_bytes(b'DO NOT TOUCH EXISTING INSTANCE')
            for mode,args in [('burst_cycles',['--cycles','1']),('paced_duration',['--duration-seconds','2','--think-ms','100'])]:
                report=root/(mode+'.json')
                result=subprocess.run([sys.executable,'tool/load_test.py','--accounts','20','--active','2','--output',str(report),*args],cwd=ROOT,
                                      env={**os.environ,'MOMIQ_DATA_DIR':str(existing),'MOMIQ_ENV':'production','MOMIQ_ALLOW_TEST_LOGIN':'0',
                                           'HTTP_PROXY':'http://127.0.0.1:1','http_proxy':'http://127.0.0.1:1','NO_PROXY':'','no_proxy':''},capture_output=True,text=True,timeout=40)
                self.assertEqual(result.returncode,0,result.stderr[-1500:])
                data=json.loads(report.read_text(encoding='utf-8'));self.assertEqual(data['mode'],mode)
                self.assertEqual(data['requests'],data['successfulRequests']);self.assertGreater(data['requests'],0)
                self.assertEqual(data['measurementVersion'],2)
                self.assertEqual(sum(e['handlerDuration']['count'] for e in data['endpoints'].values()),data['requests'])
                for endpoint in data['endpoints'].values():
                    self.assertEqual(sum(p['count'] for p in endpoint['clientPhases'].values()),endpoint['count'])
                    self.assertEqual(sum(p['count'] for p in endpoint['handlerPhases'].values()),endpoint['count'])
                    self.assertGreaterEqual(endpoint['handlerDuration']['p95Ms'],0)
                self.assertEqual(data['database']['integrity'],'ok');self.assertEqual(data['database']['bookings'],0)
                self.assertEqual(data['database']['accounts'],20);self.assertEqual(data['database']['foreignKeyErrors'],0)
                if mode=='burst_cycles':self.assertEqual(data['expectedRequests'],14)
                else:self.assertIsNone(data['expectedRequests']);self.assertGreaterEqual(data['elapsedSeconds'],2)
                self.assertNotIn('Bearer',report.read_text(encoding='utf-8'));self.assertNotIn('TEST Load',report.read_text(encoding='utf-8'))
                self.assertEqual(marker.read_bytes(),b'DO NOT TOUCH EXISTING INSTANCE')

    def test_invalid_pacing_and_existing_evidence_are_rejected_before_running(self):
        with tempfile.TemporaryDirectory() as folder:
            report=Path(folder)/'evidence.json'
            for args in (['--duration-seconds','301','--think-ms','100'],['--duration-seconds','1'],['--think-ms','100'],['--duration-seconds','-1','--think-ms','100']):
                result=subprocess.run([sys.executable,'tool/load_test.py','--output',str(report),*args],cwd=ROOT,capture_output=True,timeout=10)
                self.assertEqual(result.returncode,2);self.assertFalse(report.exists())
            report.write_text('PRESERVED EVIDENCE',encoding='utf-8')
            result=subprocess.run([sys.executable,'tool/load_test.py','--output',str(report)],cwd=ROOT,capture_output=True,timeout=10)
            self.assertEqual(result.returncode,2);self.assertEqual(report.read_text(encoding='utf-8'),'PRESERVED EVIDENCE')


if __name__=='__main__':unittest.main()
