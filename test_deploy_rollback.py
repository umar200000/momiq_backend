"""Exercise the admin failure/rollback branch with a local mirror and scratch releases."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import release_pair

ROOT = Path(__file__).resolve().parent


@unittest.skipUnless(os.name == 'posix' and shutil.which('flock'), 'Linux deployment runner')
class DeployRollbackTests(unittest.TestCase):
    def exercise(self, previous_healthy):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            repository = base / 'fixture-source'
            repository.mkdir()
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=repository, text=True).strip()
            git('init', '-q', '-b', 'main')
            for name in release_pair.ASSETS:
                (repository / name).write_text('TEST', encoding='utf-8')
            (repository / 'release-contract.json').write_text('{"backendContractVersion":1}')
            git('add', '.')
            git('-c', 'user.name=Fixture', '-c', 'user.email=test@localhost',
                '-c', 'commit.gpgsign=false', 'commit', '-qm', 'TEST release')
            sha = git('rev-parse', 'HEAD')
            mirror = base / 'git' / 'admin.git'
            mirror.parent.mkdir()
            git('clone', '-q', '--bare', str(repository), str(mirror))
            current = base / 'current'
            current.mkdir()
            old = base / 'old-admin'
            shutil.copytree(repository, old, ignore=shutil.ignore_patterns('.git'))
            (current / 'admin').symlink_to(old, target_is_directory=True)
            backend = current / 'backend'
            binary = backend / '.venv' / 'bin'
            binary.mkdir(parents=True)
            (binary / 'python').symlink_to(sys.executable)
            (backend / '.release-sha').write_text('a' * 40 + '\n')
            (backend / 'admin-release.json').write_text(json.dumps({
                'repository':'umar200000/momiq_admin', 'contractVersion':1, 'revision':sha}))
            shutil.copy(ROOT / 'release_pair.py', backend)
            (backend / 'deployment_health.py').write_text("def release_sha(path): return 'a'*40\n")
            # Stand in for localhost availability without opening a socket.
            (backend / 'deploy_smoke.py').write_text(
                "import os,sys\nfrom pathlib import Path\n"
                "base=Path(os.environ['FIXTURE_BASE'])\n"
                "assert sys.argv[sys.argv.index('--backend-sha')+1]=='a'*40\n"
                "previous=Path(sys.argv[sys.argv.index('--admin-dir')+1]).resolve()==base/'old-admin'\n"
                "with (base/'checks').open('a') as log: print(int(previous),file=log)\n"
                "sys.exit(0 if previous and os.environ['PREVIOUS_HEALTHY']=='1' else 1)\n")
            source = (ROOT / 'deploy' / 'momiq-deploy').read_text()
            script = base / 'deployer'
            self.assertEqual(source.count('base=/opt/momiq'), 1)
            self.assertEqual(source.count('exec 9>/run/lock/momiq-deploy.lock'), 1)
            script.write_text(source.replace('base=/opt/momiq', 'base="$FIXTURE_BASE"')
                              .replace('exec 9>/run/lock/momiq-deploy.lock', 'exec 9>"$FIXTURE_BASE/lock"'))
            result = subprocess.run(['bash', str(script), 'admin', sha], capture_output=True,
                                    text=True, timeout=35, env={**os.environ,'FIXTURE_BASE':folder,
                                    'PREVIOUS_HEALTHY':str(int(previous_healthy)),
                                    'GIT_ALLOW_PROTOCOL':'file','GIT_TERMINAL_PROMPT':'0'})
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual((current / 'admin').resolve(), old)
            self.assertFalse((current / 'admin.sha').exists())
            self.assertEqual((base / 'checks').read_text().splitlines(), ['0']*3 + ['1']*(1 if previous_healthy else 3))
            if previous_healthy:
                self.assertIn('restored and serving checks passed', result.stdout)
            else:
                self.assertIn('Operator recovery required', result.stderr)
                self.assertNotIn('serving checks passed', result.stdout)

    def test_failure_verifies_restored_assets(self):
        self.exercise(True)

    def test_failed_recovery_never_claims_a_healthy_deployment(self):
        self.exercise(False)
