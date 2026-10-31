"""Cross-process exclusion for backup and private-media retirement only.

Ordinary booking/wallet writes do not wait on this file lock. Uploads publish
immutable files before their DB references and need not hold the lock.
"""
from contextlib import contextmanager
import os
import stat
from pathlib import Path
import time


@contextmanager
def lock(root, timeout=30):
    root=Path(root).resolve()
    path=root/'.media-maintenance.lock'
    flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    descriptor=os.open(path,flags,0o600)
    with os.fdopen(descriptor,'r+b') as stream:
        info = os.fstat(descriptor)
        entry = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                not os.path.samestat(info, entry) or
                getattr(entry, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError('Media lock requires one private regular file')
        if os.name!='nt' and os.geteuid()==0:
            # A root backup must not strand the unprivileged API/cleanup worker
            # behind a root-owned lock. O_NOFOLLOW binds this to the opened file.
            owner=root.stat()
            os.fchown(stream.fileno(),owner.st_uid,owner.st_gid)
        if info.st_size==0:
            stream.write(b'0');stream.flush()
        deadline=time.monotonic()+timeout
        while True:
            try:
                stream.seek(0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(),fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError,PermissionError):
                if time.monotonic()>=deadline:raise TimeoutError('Media maintenance is busy')
                time.sleep(.05)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
