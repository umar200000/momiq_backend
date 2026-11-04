import os
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tool import host_audit


@unittest.skipUnless(os.name=='posix','Linux host inspection')
class HostAuditTests(unittest.TestCase):
    def test_deploy_script_requires_expected_bytes_and_safe_root_ownership(self):
        from unittest.mock import Mock
        path=Mock()
        path.read_bytes.return_value=b'tested deploy script'
        expected=hashlib.sha256(path.read_bytes.return_value).hexdigest()
        path.lstat.return_value.st_mode=0o100755
        path.lstat.return_value.st_uid=0
        self.assertTrue(host_audit.installed_deployer(path,expected))
        self.assertFalse(host_audit.installed_deployer(path,'0'*64))
        path.lstat.return_value.st_uid=1000
        self.assertFalse(host_audit.installed_deployer(path,expected))
        path.lstat.return_value.st_uid=0
        path.lstat.return_value.st_mode=0o100775
        self.assertFalse(host_audit.installed_deployer(path,expected))

    def test_private_file_checks_reject_links_and_broader_access(self):
        with TemporaryDirectory() as root:
            p=Path(root)/'instance.env'
            p.touch(mode=0o600)
            self.assertTrue(host_audit.owner_mode(p,os.getuid(),0o600))
            link=Path(root)/'link'
            link.symlink_to(p)
            self.assertFalse(host_audit.owner_mode(link,os.getuid(),0o600))
            p.chmod(0o644)
            self.assertFalse(host_audit.owner_mode(p,os.getuid(),0o600))
            self.assertIsNone(host_audit.owner_mode(Path(root)/'absent',os.getuid(),0o600))

    def test_reports_missing_and_unsafe_host_evidence(self):
        def command(*args):
            if args[0]=='ufw': return 'Status: active\nDefault: deny (incoming), allow (outgoing)'
            if args[0]=='ss': return 'LISTEN 0 512 127.0.0.1:8080 0.0.0.0:*'
            if args[:2]==('systemctl','is-active'): return 'active'
            if 'NextElapseUSecRealtime' in args: return 'Fri 2026-11-06 00:00:00 UTC'
            if 'User' in args: return 'momiq'
            if 'Restart' in args: return 'on-failure'
            return ''
        with patch.object(host_audit,'owner_mode',return_value=True):
            with patch.object(host_audit,'output',side_effect=command):
                self.assertTrue(all(host_audit.inspect().values()))
            with patch.object(host_audit,'output',return_value=None):
                checks=host_audit.inspect()
                self.assertIsNone(checks['apiLoopbackOnly'])
                self.assertIsNone(checks['firewallActive'])
                self.assertFalse(checks['renewalTimerScheduled'])
            with patch.object(host_audit,'output',return_value='LISTEN 0 512 0.0.0.0:8080 0.0.0.0:*'):
                self.assertFalse(host_audit.inspect()['apiLoopbackOnly'])
