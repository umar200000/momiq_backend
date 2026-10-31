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
    backup_bundle.verify(bundle)
    expires = backup_bundle.bundle_expiry(bundle)
    if datetime.now(timezone.utc) >= expires:
        raise ValueError('Backup retention elapsed')
    manifest = json.loads(backup_bundle.bundle_file(bundle,'manifest.json').read_text(encoding='utf-8'))
    members = ['manifest.json','momiq.sqlite3',*(item['path'] for item in manifest['files'])]
    with TemporaryDirectory(dir=destination.parent) as temp:
        encrypted = Path(temp)/'bundle.age'
        with encrypted.open('xb') as output:
            os.chmod(encrypted,0o600)
            with subprocess.Popen(['age','--encrypt','-r',recipient],stdin=subprocess.PIPE,
                                  stdout=output,stderr=subprocess.DEVNULL) as process:
                try:
                    with zipfile.ZipFile(_ArchiveSink(process.stdin),'w',compression=zipfile.ZIP_STORED) as archive:
                        for name in members:
                            with backup_bundle.bundle_file(bundle,name).open('rb') as src, archive.open(name,'w',force_zip64=True) as dst:
                                shutil.copyfileobj(src,dst)
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
        # Atomic publication without replacing an existing export on concurrent runs.
        os.link(encrypted,destination)
    return {'sha256':checksum,'bytes':size,'expiresAt':expires.isoformat()}


def drill(encrypted, identity, checksum, mode, max_bytes=8*1024**3):
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
    args = parser.parse_args()
    try:
        result = (seal(args.bundle,args.destination,args.recipient) if args.action=='seal'
                  else drill(args.encrypted,args.identity,args.sha256,args.mode,args.max_bytes))
        print(json.dumps(result))
    except Exception:
        parser.exit(1, 'Encrypted backup operation failed\n')
