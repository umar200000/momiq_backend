"""Seal a verified Momiq backup for transfer, or rehearse recovery offline."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from time import monotonic
from tempfile import TemporaryDirectory
import zipfile

import backup_bundle
import restore_drill


class _ArchiveSink:
    # Windows pipes may expose tell() without reporting a usable ZIP offset.
    def __init__(self, pipe):
        self.write = pipe.write
        self.flush = pipe.flush


def seal(bundle, destination, recipient):
    bundle = Path(bundle).resolve(strict=True)
    destination = Path(destination).absolute()
    if (not re.fullmatch(r'age1[0-9a-z]{58}',recipient) or destination.exists() or
            destination.is_symlink() or destination.resolve().is_relative_to(bundle)):
        raise ValueError('Choose a native X25519 public recipient and a new destination outside the bundle')
    manifest_bytes = backup_bundle.bundle_file(bundle,'manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes.decode('utf-8'))
    backup_bundle.verify(bundle,manifest=manifest)
    expires = backup_bundle.bundle_expiry(bundle,manifest=manifest)
    if datetime.now(timezone.utc) >= expires:
        raise ValueError('Backup retention elapsed')
    if datetime.fromisoformat(manifest['created']) > datetime.now(timezone.utc):
        raise ValueError('Backup snapshot is future-dated')
    members = {'momiq.sqlite3': manifest['databaseSha256'],
               **{item['path']:item['sha256'] for item in manifest['files']}}
    with TemporaryDirectory(dir=destination.parent) as temp:
        encrypted = Path(temp)/'bundle.age'
        with encrypted.open('xb') as output:
            os.chmod(encrypted,0o600)
            with subprocess.Popen(['age','--encrypt','-r',recipient],stdin=subprocess.PIPE,
                                  stdout=output,stderr=subprocess.DEVNULL) as process:
                try:
                    with zipfile.ZipFile(_ArchiveSink(process.stdin),'w',compression=zipfile.ZIP_STORED) as archive:
                        archive.writestr('manifest.json',manifest_bytes)
                        for name,expected in members.items():
                            digest = hashlib.sha256()
                            with backup_bundle.bundle_file(bundle,name).open('rb') as src, archive.open(name,'w',force_zip64=True) as dst:
                                while chunk := src.read(1024*1024):
                                    digest.update(chunk)
                                    dst.write(chunk)
                            if digest.hexdigest() != expected:
                                raise ValueError('Backup member changed during encryption')
                    process.stdin.close()
                    if process.wait():
                        raise ValueError('Encryption failed')
                finally:
                    if process.poll() is None:
                        process.kill()
            output.flush()
            os.fsync(output.fileno())
        checksum = backup_bundle.digest(encrypted)
        size = encrypted.stat().st_size
        if datetime.now(timezone.utc) >= expires:
            raise ValueError('Backup retention elapsed during encryption')
        # Atomic publication without replacing an existing export on concurrent runs.
        os.link(encrypted,destination)
    return {'sha256':checksum,'bytes':size,'createdAt':manifest['created'],'expiresAt':expires.isoformat()}


def inspect_copy(encrypted, receipt, *, max_age_hours, min_bytes, max_bytes, now=None):
    """Check a locally accessible offsite copy without a private decryption key."""
    if not 0 < max_age_hours <= 24*365 or not 0 < min_bytes <= max_bytes:
        raise ValueError('Invalid verification limits')
    if (not isinstance(receipt,dict) or type(receipt.get('bytes')) is not int or
            not re.fullmatch('[0-9a-f]{64}',receipt.get('sha256',''))):
        raise ValueError('Invalid backup receipt')
    created, expires = (datetime.fromisoformat(receipt[k]) for k in ('createdAt','expiresAt'))
    if created.tzinfo is None or expires.tzinfo is None or expires <= created:
        raise ValueError('Invalid backup interval')
    now = now or datetime.now(timezone.utc)
    age = (now-created).total_seconds()
    if age < 0 or age > max_age_hours*3600 or now >= expires:
        raise ValueError('Backup is stale, expired or future-dated')
    path = Path(encrypted)
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected a ciphertext file')
    with path.open('rb') as stream:
        size = os.fstat(stream.fileno()).st_size
        if size != receipt['bytes'] or not min_bytes <= size <= max_bytes:
            raise ValueError('Unexpected backup size')
        if hashlib.file_digest(stream,'sha256').hexdigest() != receipt['sha256']:
            raise ValueError('Ciphertext digest mismatch')
    return {'ok':True,'ageSeconds':round(age,2),'bytes':size,'expiresAt':expires.isoformat()}


def drill(encrypted, identity, checksum, mode, max_bytes=8*1024**3):
    started=monotonic()
    encrypted = Path(encrypted).resolve(strict=True)
    if (not re.fullmatch('[0-9a-f]{64}',checksum) or not 0 < encrypted.stat().st_size <= max_bytes or
            not mode in ('local','test','staging','production')):
        raise ValueError('Invalid recovery inputs')
    with TemporaryDirectory(prefix='momiq-age-drill-') as temp:
        root = Path(temp)
        plain = root/'decrypted.zip'
        with encrypted.open('rb') as ciphertext:
            if hashlib.file_digest(ciphertext,'sha256').hexdigest() != checksum:
                raise ValueError('Ciphertext digest mismatch')
            ciphertext.seek(0)
            with subprocess.Popen(['age','--decrypt','-i',str(Path(identity).resolve(strict=True))],
                                  stdin=ciphertext,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL) as process:
                try:
                    with plain.open('xb') as output:
                        written = 0
                        while chunk := process.stdout.read(1024*1024):
                            written += len(chunk)
                            if written > max_bytes:
                                raise ValueError('Decrypted backup exceeds recovery limit')
                            output.write(chunk)
                    if process.wait():
                        raise ValueError('Decryption failed')
                finally:
                    if process.poll() is None:
                        process.kill()
        restored = root/'bundle'
        restored.mkdir(mode=0o700)
        with zipfile.ZipFile(plain) as archive:
            members = archive.infolist()
            if (len(members)>100002 or sum(m.file_size for m in members)>max_bytes or
                    len(set(m.filename for m in members))!=len(members)):
                raise ValueError('Invalid archive size or duplicate member')
            for member in members:
                if (member.compress_type != zipfile.ZIP_STORED or not re.fullmatch(
                        r'manifest\.json|momiq\.sqlite3|care-videos/[a-f0-9]{32}/(?:playback\.mp4|poster\.jpg)',member.filename)):
                    raise ValueError('Unexpected encrypted backup member')
                target = restored/member.filename
                target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                with archive.open(member) as src, target.open('xb') as dst:
                    shutil.copyfileobj(src,dst)
        plain.unlink()
        result = restore_drill.rehearse(restored,mode)
        if len(members)!=result['mediaFiles']+2:
            raise ValueError('Unreferenced media in encrypted backup')
    result['drillSeconds']=monotonic()-started
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action',required=True)
    create = commands.add_parser('seal')
    for option in ('bundle','destination','recipient'):
        create.add_argument('--'+option,required=True)
    restore = commands.add_parser('drill')
    for option in ('encrypted','identity','sha256','mode'):
        restore.add_argument('--'+option,required=True)
    restore.add_argument('--max-bytes',type=int,default=8*1024**3)
    restore.add_argument('--max-snapshot-age-seconds',type=int)
    restore.add_argument('--max-drill-seconds',type=int)
    inspect = commands.add_parser('inspect')
    for option in ('encrypted','receipt'):
        inspect.add_argument('--'+option,required=True)
    for option in ('max-age-hours','min-bytes','max-bytes'):
        inspect.add_argument('--'+option,required=True,type=int)
    args = parser.parse_args()
    try:
        if args.action=='seal':
            result = seal(args.bundle,args.destination,args.recipient)
        elif args.action=='inspect':
            receipt = json.loads(Path(args.receipt).read_text(encoding='utf-8-sig'))
            result = inspect_copy(args.encrypted,receipt,max_age_hours=args.max_age_hours,
                                  min_bytes=args.min_bytes,max_bytes=args.max_bytes)
        else:
            result = drill(args.encrypted,args.identity,args.sha256,args.mode,args.max_bytes)
            result.update(restore_drill.recovery_status(result,args.max_snapshot_age_seconds,args.max_drill_seconds))
        print(json.dumps(result))
        if result.get('breached'):raise SystemExit(2)
    except Exception:
        parser.exit(1, 'Encrypted backup operation failed\n')
