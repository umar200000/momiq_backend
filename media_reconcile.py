"""Inspect unpublished video derivatives and optionally purge only known orphan files."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
import stat
import time

import deployment_health
import media_maintenance


def regular_entry(path, directory=False):
    entry = path.lstat()
    if getattr(entry, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        return False
    return stat.S_ISDIR(entry.st_mode) if directory else stat.S_ISREG(entry.st_mode) and entry.st_nlink == 1


def reconcile(data, mode, *, purge=False, min_age_hours=24, limit=100):
    if mode not in {'local','test','staging','production'} or not 1 <= min_age_hours <= 8760 or not 1 <= limit <= 1000:
        raise ValueError('Invalid reconciliation parameters')
    data = Path(data).resolve(strict=True)
    database = data/'momiq.sqlite3'
    if not regular_entry(database):
        raise ValueError('Invalid instance database')
    deployment_health.check_database(data, mode)
    counts = dict(referenced=0, orphan=0, recent=0, unsafe=0, temporary=0, purged=0)
    root = data/'care-videos'
    try:
        if not regular_entry(root, directory=True):
            raise ValueError('Unsafe media root')
    except FileNotFoundError:
        return counts
    cutoff = time.time() - min_age_hours * 3600
    uri = database.as_uri() + ('?mode=rw' if purge else '?mode=ro')
    # Uploads create the final ID directory only after acquiring the same SQLite
    # writer lock. A queued writer must commit or roll back before classification.
    with media_maintenance.lock(data), closing(sqlite3.connect(uri, uri=True, timeout=10)) as con:
        for folder in root.iterdir():
            if folder.name.startswith(('.upload-', '.processing-')):
                counts['temporary'] += 1
                continue
            if not re.fullmatch(r'[0-9a-f]{32}', folder.name):
                counts['unsafe'] += 1
                continue
            with con:
                con.execute('BEGIN IMMEDIATE' if purge else 'BEGIN')
                if con.execute('SELECT 1 FROM booking_videos WHERE id=?', (folder.name,)).fetchone():
                    counts['referenced'] += 1
                    continue
                try:
                    valid_folder = regular_entry(folder, directory=True)
                except FileNotFoundError:
                    continue  # A failed upload removed its temporary publication.
                if not valid_folder or folder.resolve().parent != root:
                    counts['unsafe'] += 1
                    continue
                files = list(folder.iterdir())
                if any(f.name not in ('playback.mp4','poster.jpg') or not regular_entry(f) for f in files):
                    counts['unsafe'] += 1
                    continue
                if max(p.lstat().st_mtime for p in [folder, *files]) > cutoff:
                    counts['recent'] += 1
                    continue
                counts['orphan'] += 1
                if purge and counts['purged'] < limit:
                    for path in files:
                        path.unlink()
                    folder.rmdir()
                    counts['purged'] += 1
    return counts


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', required=True, type=Path)
    parser.add_argument('--mode', required=True, choices=('local','test','staging','production'))
    parser.add_argument('--min-age-hours', type=int, default=24)
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--purge', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(reconcile(args.data, args.mode, purge=args.purge,
                                   min_age_hours=args.min_age_hours, limit=args.limit)))
    except (OSError, sqlite3.Error, ValueError, TimeoutError):
        parser.exit(1, 'Private media reconciliation failed\n')
