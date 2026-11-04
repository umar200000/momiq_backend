"""Inspect the installed Momiq Linux service without reading secrets or restarting it."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess


def output(*command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10,
                                env={**os.environ, 'LC_ALL':'C'})
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode==0 else None


def owner_mode(path, uid, mode, *, directory=False):
    try:
        info = Path(path).lstat()
    except OSError:
        return None
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    return expected(info.st_mode) and info.st_uid==uid and stat.S_IMODE(info.st_mode)==mode


def installed_deployer(path, expected):
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode & 0o022:
            return False
        return hashlib.sha256(path.read_bytes()).hexdigest()==expected
    except OSError:
        return None


def inspect(deployer_sha=None):
    import pwd
    try:
        uid = pwd.getpwnam('momiq').pw_uid
    except KeyError:
        uid = None
    firewall = output('ufw','status','verbose')
    listeners = output('ss','-H','-ltn','sport = :8080')
    addresses = [line.split()[3] for line in (listeners or '').splitlines() if len(line.split())>=4]
    checks = {
        'apiActive': output('systemctl','is-active','momiq.service')=='active',
        'nginxActive': output('systemctl','is-active','nginx.service')=='active',
        'nginxConfigurationValid': output('nginx','-t') is not None,
        'apiUser': output('systemctl','show','momiq.service','-p','User','--value')=='momiq',
        'restartOnFailure': output('systemctl','show','momiq.service','-p','Restart','--value')=='on-failure',
        'apiLoopbackOnly': None if listeners is None else bool(addresses) and all(
            addr in ('127.0.0.1:8080','[::1]:8080') for addr in addresses),
        'firewallActive': None if firewall is None else 'Status: active' in firewall.splitlines(),
        'incomingDefaultDeny': None if firewall is None else bool(
            re.search(r'^Default: (deny|reject) \(incoming\)',firewall,re.M)),
        'environmentRoot0600': owner_mode('/etc/momiq/backend.env',0,0o600),
        'runtimePrivate0700': owner_mode('/var/lib/momiq',uid,0o700,directory=True),
        'databasePrivate0600': owner_mode('/var/lib/momiq/momiq.sqlite3',uid,0o600),
        'backupTimerActive': output('systemctl','is-active','momiq-backup.timer')=='active',
    }
    timers = ('certbot.timer','snap.certbot.renew.timer')
    checks['renewalTimerScheduled'] = any(
        output('systemctl','is-active',unit)=='active' and
        output('systemctl','show',unit,'-p','NextElapseUSecRealtime','--value') not in (None,'','n/a','0')
        for unit in timers)
    if deployer_sha is not None:
        checks['reviewedDeployerInstalled'] = installed_deployer(Path('/usr/local/sbin/momiq-deploy'),deployer_sha)
    return checks


if __name__=='__main__':
    if os.name!='posix' or os.geteuid()!=0:
        raise SystemExit('Run from the authorized root console on the Momiq Linux host')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deploy-sha256',help='Digest of the reviewed deploy script for this host')
    args=parser.parse_args()
    if args.deploy_sha256 and not re.fullmatch(r'[0-9a-f]{64}',args.deploy_sha256):
        parser.error('Expected a full lowercase SHA-256')
    checks = inspect(args.deploy_sha256)
    print(json.dumps(checks,sort_keys=True))
    raise SystemExit(0 if all(checks.values()) else 1)
