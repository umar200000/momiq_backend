"""Run the actual bootstrap preflight and site install inside scratch paths."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.name == 'posix', 'Linux bootstrap runner')
class BootstrapSiteTests(unittest.TestCase):
    def test_existing_tls_site_survives_the_reviewed_bootstrap(self):
        source = (Path(__file__).parent / 'deploy/bootstrap.sh').read_text()
        preflight = source[:source.index('apt-get update')]
        site_install = source[source.index('if [[ "$preserve_site" == false'):]
        site_install = site_install[:site_install.index('(umask')]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bootstrap = root / 'bootstrap'
            bootstrap.write_text(preflight.replace('/home/ubuntu/momiq-bootstrap', '"$ROOT"')
                                 .replace('/etc/nginx/sites-available/momiq', '"$ROOT/site"')
                                 .replace('/etc/nginx/sites-enabled/momiq', '"$ROOT/enabled"')
                                 + site_install)
            template, site = root / 'nginx.conf', root / 'site'
            template.write_text('TEST HTTP template')
            def run(*args):
                return subprocess.run(['bash', str(bootstrap), *args], capture_output=True,
                                      env={**os.environ, 'ROOT': folder}).returncode
            self.assertEqual(run(), 0)
            self.assertEqual(site.read_bytes(), template.read_bytes())
            self.assertEqual(run(), 0)
            (root / 'enabled').symlink_to(site)
            site.write_text('TEST operator config with Certbot TLS directives')
            self.assertEqual(run(), 69)
            self.assertEqual(run('--typo'), 64)
            self.assertEqual(run('--preserve-reviewed-nginx'), 0)
            self.assertEqual(site.read_text(), 'TEST operator config with Certbot TLS directives')
            (root / 'enabled').unlink()
            (root / 'enabled').write_text('TEST unmanaged regular site')
            self.assertEqual(run('--preserve-reviewed-nginx'), 69)
