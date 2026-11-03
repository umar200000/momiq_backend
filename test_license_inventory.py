from email.message import Message
import hashlib
from pathlib import Path
import tempfile
import unittest

from tool.license_inventory import collect


class FakeDistribution:
    version = '1.2.3'

    def __init__(self, root):
        self.root = root
        self.metadata = Message()
        self.metadata['Name'] = 'example-lib'
        self.metadata['License-File'] = 'LICENSE'
        self.files = ['example_lib-1.2.3.dist-info/licenses/LICENSE']
        path = root/self.files[0]
        path.parent.mkdir(parents=True)
        path.write_bytes(b'Copyright example\nExample license\n')

    def locate_file(self, path):
        return self.root/path


class LicenseInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.lock = self.root/'requirements.lock'
        self.lock.write_text('example_lib==1.2.3 \\\n    --hash=sha256:abc\n', encoding='utf-8')
        self.dist = FakeDistribution(self.root)

    def collect(self):
        return collect(self.lock, lambda _: self.dist)

    def test_exact_identity_and_full_notices_without_machine_paths(self):
        result, notices = self.collect()
        self.assertFalse(result['legalApproval'])
        self.assertEqual(result['lockSha256'], hashlib.sha256(self.lock.read_bytes()).hexdigest())
        file = result['packages'][0]['licenseFiles'][0]
        self.assertEqual(file['sha256'], hashlib.sha256(b'Copyright example\nExample license\n').hexdigest())
        self.assertIn('Example license', notices)
        self.assertNotIn(str(self.root), str(result)+notices)

    def test_missing_declared_license_and_version_mismatch_fail(self):
        self.dist.version = '1.2.4'
        with self.assertRaisesRegex(ValueError, 'differs'):
            self.collect()
        self.dist.version = '1.2.3'
        self.dist.metadata['License-File'] = 'MISSING'
        with self.assertRaisesRegex(ValueError, 'missing'):
            self.collect()

    def test_escape_and_empty_license_fail(self):
        self.dist.metadata.replace_header('License-File', '../private.env')
        with self.assertRaisesRegex(ValueError, 'escapes'):
            self.collect()
        self.dist.metadata.replace_header('License-File', 'LICENSE')
        (self.root/self.dist.files[0]).write_text('  ', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Empty'):
            self.collect()

    def test_new_unsupported_or_duplicate_requirement_is_not_omitted(self):
        for suffix in ('\nother>=1', '\n-r other.txt', '\nexample-lib==1.2.3'):
            with self.subTest(suffix=suffix):
                self.lock.write_text('example_lib==1.2.3'+suffix, encoding='utf-8')
                with self.assertRaises(ValueError):
                    self.collect()


if __name__ == '__main__':
    unittest.main()
