"""Copy one verified age ciphertext to an operator-mounted backup volume."""
import argparse
import json
import os
from pathlib import Path
import stat
import sys

import backup_bundle
import encrypted_backup
import media_maintenance


def destination(mount, source):
    mount=Path(mount).absolute()
    if mount.resolve(strict=True)!=mount or not mount.is_mount() or mount.stat().st_dev==source.stat().st_dev:
        raise ValueError('A separate mounted volume is required')
    folder=mount/'momiq-encrypted'
    folder.mkdir(mode=0o700,exist_ok=True)
    if folder.resolve(strict=True)!=folder or not folder.is_dir() or folder.stat().st_dev!=mount.stat().st_dev:
        raise ValueError('Invalid mounted backup directory')
    return folder


def sync_directory(folder):
    if os.name=='posix':
        descriptor=os.open(folder,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(descriptor)
        finally:os.close(descriptor)


def replicate(source, receipt, mount, *, max_age_hours, max_bytes):
    source=Path(source)
    limits={'max_age_hours':max_age_hours,'min_bytes':1,'max_bytes':max_bytes}
    encrypted_backup.inspect_copy(source,receipt,**limits)
    with source.open('rb') as src:
        if src.readline(23)!=b'age-encryption.org/v1\n':
            raise ValueError('Expected an age ciphertext')
    folder=destination(mount,source)
    checksum=receipt['sha256']
    final=folder/(checksum+'.age')
    partial=folder/(checksum+'.partial')
    with media_maintenance.lock(folder):
        # Only this receipt's interrupted ciphertext may be discarded. The
        # shared lock also serializes retries after a process exits mid-copy.
        if partial.exists() or partial.is_symlink():
            info=partial.lstat()
            if (not stat.S_ISREG(info.st_mode) or getattr(info,'st_file_attributes',0)&stat.FILE_ATTRIBUTE_REPARSE_POINT
                    or (info.st_nlink!=1 and not (final.exists() and partial.samefile(final)))):
                raise ValueError('Unexpected partial copy')
            partial.unlink()
        existed=final.exists() or final.is_symlink()
        if not existed:
            dst=partial.open('xb')
            try:
                with dst,source.open('rb') as src:
                    os.chmod(partial,0o600)
                    written=0
                    while chunk:=src.read(1024*1024):
                        written+=len(chunk)
                        if written>receipt['bytes']:raise ValueError('Source grew during copy')
                        dst.write(chunk)
                    dst.flush()
                    os.fsync(dst.fileno())
                encrypted_backup.inspect_copy(partial,receipt,**limits)
                os.link(partial,final)
            finally:
                partial.unlink(missing_ok=True)
        verified=encrypted_backup.inspect_copy(backup_bundle.bundle_file(folder,final.name),receipt,**limits)
        sync_directory(folder)
        return {**verified,'sha256':checksum,'alreadyPresent':existed}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('encrypted','receipt','mount'):
        parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--max-age-hours',required=True,type=int)
    parser.add_argument('--max-bytes',required=True,type=int)
    args=parser.parse_args()
    try:
        receipt=json.loads(args.receipt.read_text(encoding='utf-8-sig'))
        print(json.dumps(replicate(args.encrypted,receipt,args.mount,
                                   max_age_hours=args.max_age_hours,max_bytes=args.max_bytes)))
    except (OSError,ValueError,KeyError,TypeError):
        print('Offsite ciphertext transfer failed',file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
