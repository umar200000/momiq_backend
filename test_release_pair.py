import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import release_pair

ROOT=Path(__file__).resolve().parent


class ReleasePairTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='momiq release test ');self.addCleanup(temp.cleanup)
        self.backend=Path(temp.name)/'backend';self.admin=Path(temp.name)/'admin'
        self.backend.mkdir();self.admin.mkdir()
        self.pin={'repository':'umar200000/momiq_admin','revision':'a'*40,'contractVersion':1}
        self.write_pin(self.pin)
        (self.admin/'release-contract.json').write_text('{"backendContractVersion":1}',encoding='utf-8')
        for name in release_pair.ASSETS:(self.admin/name).write_text('TEST fixture',encoding='utf-8')

    def write_pin(self,pin):
        (self.backend/'admin-release.json').write_text(json.dumps(pin),encoding='utf-8')

    def test_compatible_assets_and_exact_ci_revision_have_distinct_checks(self):
        self.assertEqual(release_pair.validate(self.backend,self.admin),self.pin)
        self.assertEqual(release_pair.validate(self.backend,self.admin,'a'*40),self.pin)
        with self.assertRaisesRegex(ValueError,'exact revision'):release_pair.validate(self.backend,self.admin,'b'*40)

    def test_legacy_mismatch_and_incomplete_panels_fail_closed(self):
        manifest=self.admin/'release-contract.json';manifest.unlink()
        with self.assertRaises(FileNotFoundError):release_pair.validate(self.backend,self.admin)
        for value in ([],{'backendContractVersion':True},{'backendContractVersion':2},{'backendContractVersion':1,'ignoreMismatch':True}):
            manifest.write_text(json.dumps(value),encoding='utf-8')
            with self.assertRaises(ValueError):release_pair.validate(self.backend,self.admin)
        manifest.write_text('{"backendContractVersion":1}',encoding='utf-8')
        asset=self.admin/'work_queue.js';asset.write_text('',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'work_queue.js'):release_pair.validate(self.backend,self.admin)
        asset.unlink()
        with self.assertRaises(ValueError):release_pair.validate(self.backend,self.admin)

    def test_untrusted_pin_fields_duplicate_keys_and_oversize_are_rejected(self):
        for field,value in [('revision','main'),('revision','a'*40+'\nforged=x'),('revision',True),('repository','other/repo'),('contractVersion',True),('contractVersion',2)]:
            self.write_pin({**self.pin,field:value})
            with self.assertRaises(ValueError):release_pair.admin_pin(self.backend)
        path=self.backend/'admin-release.json'
        for text in ('{"revision":"a","revision":"b"}',' '*4097):
            path.write_text(text,encoding='utf-8')
            with self.assertRaises(ValueError):release_pair.admin_pin(self.backend)

    def test_cli_emits_only_valid_pin_and_failure_has_no_checkout_output(self):
        command=[sys.executable,str(ROOT/'release_pair.py'),'--backend',str(self.backend)]
        result=subprocess.run([*command,'--print-revision'],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0);self.assertEqual(result.stdout,'a'*40+'\n')
        result=subprocess.run([*command,'--admin',str(self.admin),'--actual-admin-revision','b'*40],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,1);self.assertEqual(result.stdout,'')
        self.write_pin({**self.pin,'revision':'main'})
        result=subprocess.run([*command,'--print-revision'],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,1);self.assertEqual(result.stdout,'')


if __name__=='__main__':unittest.main()
