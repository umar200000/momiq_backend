"""Bounded read-only readiness; never bootstrap, migrate or create a database."""
import argparse
from contextlib import closing
import hashlib
from pathlib import Path
import re
import sqlite3

from migrations import MIGRATIONS


def release_sha(root):
    path = Path(root) / '.release-sha'
    if not path.exists():
        return None  # A development checkout has no deployment identity.
    raw = path.read_bytes()
    if not re.fullmatch(rb'[a-f0-9]{40}\n?', raw):
        raise ValueError('Invalid release identity')
    return raw.decode().strip()


def check_database(data, environment):
    expected = {version: hashlib.sha256('\n'.join(statements).encode()).hexdigest()
                for version, _, statements in MIGRATIONS}
    path = Path(data).resolve() / 'momiq.sqlite3'
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)) as con:
        con.execute('PRAGMA query_only=ON')
        con.execute('BEGIN')
        mode = con.execute("SELECT value FROM runtime_metadata WHERE key='environment'").fetchone()
        if mode != (environment,):
            raise ValueError('Database environment mismatch')
        if dict(con.execute('SELECT version,checksum FROM schema_migrations')) != expected:
            raise ValueError('Database migration mismatch')
        # Exercise essential reads without counts, scans or personal response data.
        for query in (
            'SELECT id,blocked FROM users LIMIT 0',
            'SELECT hash,role,expires FROM sessions LIMIT 0',
            'SELECT user_id,data FROM listings LIMIT 0',
            'SELECT user_id,service,status FROM listing_moderation LIMIT 0',
            'SELECT user_id,balance_minor FROM wallet_accounts LIMIT 0',
            'SELECT id,status FROM bookings LIMIT 0',
            'SELECT message_id,ticket_id,source_version FROM support_resolutions LIMIT 0',
        ):
            con.execute(query)
    return max(expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--mode', choices=('local', 'test', 'staging', 'production'), required=True)
    args = parser.parse_args()
    try:
        version = check_database(args.data, args.mode)
    except (OSError, ValueError, sqlite3.Error):
        parser.exit(1, 'Database readiness failed; no changes made\n')
    print('Read-only database compatibility verified; schema', version)


if __name__ == '__main__':
    main()
