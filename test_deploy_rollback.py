"""Exercise the admin failure/rollback branch with a local mirror and scratch releases."""
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tempfile
import unittest

import release_pair

ROOT = Path(__file__).resolve().parent


@unittest.skipUnless(os.name == 'posix' and shutil.which('flock'), 'Linux deployment runner')
class DeployRollbackTests(unittest.TestCase):
    def test_backend_timer_failure_rolls_back_verified_code_without_publishing_success_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);repo=root/'fixture-source';repo.mkdir()
            def git(*args):
                return subprocess.check_output(['git',*args],cwd=repo,text=True).strip()
            git('init','-q','-b','main')
            smoke="import os\nfrom pathlib import Path\nr=Path(os.environ['FIXTURE_BASE'])\nwith (r/'checks').open('a') as f: print(Path(__file__).resolve().parent.name,file=f)\n"
            for name,content in {'deploy_smoke.py':smoke,'server.py':'def setup(): pass',
                                 'session_maintenance.py':'','release_pair.py':'','requirements.txt':'',
                                 'predeploy_backup.py':"print('{}')",
                                 'test_fixture.py':"import unittest,server\nclass Fixture(unittest.TestCase):\n def test_setup(self): self.assertIsNone(server.setup())"}.items():
                (repo/name).write_text(content)
            git('add','.');git('-c','user.name=Fixture','-c','user.email=test@localhost',
                              '-c','commit.gpgsign=false','commit','-qm','TEST')
            sha=git('rev-parse','HEAD')
            (root/'git').mkdir();git('clone','-q','--bare',str(repo),str(root/'git/backend.git'))
            old=root/'previous';(old/'.venv/bin').mkdir(parents=True)
            (old/'.venv/bin/python').symlink_to(sys.executable)
            (old/'.release-sha').write_text('a'*40)
            (old/'deploy_smoke.py').write_text(smoke)
            (old/'deployment_health.py').write_text("import os\nfrom pathlib import Path\n(Path(os.environ['FIXTURE_BASE'])/'compatible').touch()")
            current=root/'current';current.mkdir();(current/'backend').symlink_to(old,target_is_directory=True)
            (current/'admin').mkdir();(current/'backend.sha').write_text('a'*40)
            (root/'backend.env').write_text('MOMIQ_ENV=production\nMOMIQ_DATA_DIR="$FIXTURE_BASE/data"\n')
            helpers=root/'bin';helpers.mkdir()
            python=shlex.quote(sys.executable)
            commands={'python3':f'''if [[ "$1 $2" == "-m venv" ]]; then
                mkdir -p "$3/bin"; ln -s {python} "$3/bin/python"; ln -s /bin/true "$3/bin/pip"
                else exec {python} "$@"; fi''',
                      'runuser':'[[ "$1 $2 $3" == "-u momiq --" ]] || exit 9; shift 3; exec "$@"',
                      'systemctl':'''echo "$*" >> "$FIXTURE_BASE/systemctl"
                        if [[ "$1" == start ]]; then exit 1; fi''',
                      'ffmpeg':'exit 0','ffprobe':'exit 0'}
            for command,body in commands.items():
                helper=helpers/command;helper.write_text('#!/bin/bash\nset -eu\n'+body+'\n');helper.chmod(0o700)
            script=root/'deployer'
            script.write_text((ROOT/'deploy/momiq-deploy').read_text().replace('base=/opt/momiq','base="$FIXTURE_BASE"')
                              .replace('/run/lock/momiq-deploy.lock','"$FIXTURE_BASE/lock"')
                              .replace('/etc/momiq/backend.env','"$FIXTURE_BASE/backend.env"'))
            result=subprocess.run(['bash',script,'backend',sha],capture_output=True,text=True,timeout=30,
                                  env={**os.environ,'FIXTURE_BASE':tmp,'PATH':str(helpers)+':'+os.environ['PATH'],
                                       'GIT_ALLOW_PROTOCOL':'file','GIT_TERMINAL_PROMPT':'0'})
            self.assertEqual(result.returncode,1,result.stderr)
            self.assertIn('maintenance timer failed',result.stderr)
            self.assertIn('restored and serving checks passed',result.stdout)
            self.assertTrue((root/'compatible').exists())
            self.assertEqual((current/'backend').resolve(),old)
            self.assertEqual((current/'backend.sha').read_text(),'a'*40)
            self.assertEqual((root/'checks').read_text().splitlines()[-1],old.name)
            self.assertIn('momiq-session-maintenance.timer',(root/'systemctl').read_text())

    def exercise(self, previous_healthy, *, stall=False):
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
                "if not previous and os.environ['TEST_STALL']=='1': __import__('time').sleep(60)\n"
                "sys.exit(0 if previous and os.environ['PREVIOUS_HEALTHY']=='1' else 1)\n")
            source = (ROOT / 'deploy' / 'momiq-deploy').read_text()
            script = base / 'deployer'
            self.assertEqual(source.count('base=/opt/momiq'), 1)
            self.assertEqual(source.count('exec 9>/run/lock/momiq-deploy.lock'), 1)
            script.write_text(source.replace('smoke_timeout=40s','smoke_timeout=1s').replace('base=/opt/momiq', 'base="$FIXTURE_BASE"')
                              .replace('exec 9>/run/lock/momiq-deploy.lock', 'exec 9>"$FIXTURE_BASE/lock"'))
            result = subprocess.run(['bash', str(script), 'admin', sha], capture_output=True,
                                    text=True, timeout=35, env={**os.environ,'FIXTURE_BASE':folder,
                                    'PREVIOUS_HEALTHY':str(int(previous_healthy)),
                                    'TEST_STALL':str(int(stall)),
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

    def test_stalled_smoke_times_out_and_checks_the_previous_release(self):
        self.exercise(True,stall=True)

    def test_failed_recovery_never_claims_a_healthy_deployment(self):
        self.exercise(False)
