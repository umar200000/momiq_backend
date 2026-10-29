"""Require a verified DB/private-media snapshot before an existing instance upgrade."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import re
import secrets
import sqlite3

import backup_bundle
from migrations import MIGRATIONS


def create(data, backup_root, revision, mode):
    if not isinstance(revision, str) or not re.fullmatch(r'[a-f0-9]{40}', revision):
        raise ValueError('A full release revision is required')
    data, backup_root = Path(data).resolve(), Path(backup_root).resolve()
    if data.is_relative_to(backup_root) or backup_root.is_relative_to(data):
        raise ValueError('Runtime and backup directories must be separate')
    if not (data / 'momiq.sqlite3').is_file():
        raise ValueError('Existing database required; initial bootstrap is a separate operation')
    if mode not in ('local', 'test', 'staging', 'production'):
        raise ValueError('Explicit valid environment required')
    with closing(sqlite3.connect((data / 'momiq.sqlite3').as_uri() + '?mode=ro', uri=True, timeout=2)) as con:
        con.execute('BEGIN')
        if con.execute("SELECT value FROM runtime_metadata WHERE key='environment'").fetchone() != (mode,):
            raise ValueError('Existing database environment mismatch')
        applied = dict(con.execute('SELECT version,checksum FROM schema_migrations'))
        expected = {version: hashlib.sha256('\n'.join(statements).encode()).hexdigest()
                    for version, _, statements in MIGRATIONS[:len(applied)]}
        if not applied or applied != expected:
            raise ValueError('Existing migration history is not a known contiguous prefix')
    # Same name/manifest format as the normal retention-aware backup rotation.
    name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + secrets.token_hex(4)
    target = backup_root / name
    verified = backup_bundle.create(data, target)
    return {'releaseSha': revision, 'backupName': name, 'schemaBefore': max(applied), 'verified': verified}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--backup-root', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--mode', required=True, choices=('local', 'test', 'staging', 'production'))
    args = parser.parse_args()
    try:
        result = create(args.data, args.backup_root, args.revision, args.mode)
    except Exception:
        # No database paths, private media identifiers or underlying contents in logs.
        parser.exit(1, 'Pre-migration backup failed; migration must not proceed\n')
    print(json.dumps(result, separators=(',', ':')))


if __name__ == '__main__':
    main()
