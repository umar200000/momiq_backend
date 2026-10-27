"""Ordered, transactional SQLite upgrades, also usable on an offline copy."""
import argparse
import hashlib
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


MIGRATIONS = (
    (1, 'account revisions', (
        'CREATE TABLE account_revisions(user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0))',
        'INSERT INTO account_revisions(user_id) SELECT id FROM users',
    )),
)


def migrate(con):
    if con.in_transaction:
        raise RuntimeError('Commit bootstrap before running migrations')
    con.execute('BEGIN IMMEDIATE')
    try:
        con.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)')
        applied = dict(con.execute('SELECT version, checksum FROM schema_migrations'))
        if set(applied) - {item[0] for item in MIGRATIONS}:
            raise RuntimeError('Database schema is newer than this application')
        completed = []
        for version, name, statements in MIGRATIONS:
            digest = hashlib.sha256('\n'.join(statements).encode()).hexdigest()
            if version in applied:
                if applied[version] != digest:
                    raise RuntimeError(f'Migration {version} checksum changed')
                continue
            for statement in statements:
                con.execute(statement)
            con.execute('INSERT INTO schema_migrations VALUES(?,?,?,?)',
                        (version, name, digest, datetime.now(timezone.utc).isoformat()))
            completed.append(version)
        con.commit()
        return completed
    except BaseException:
        con.rollback()
        raise


def backup_database(source, destination):
    """SQLite online backup includes committed WAL pages; never overwrite a backup."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_file():
        raise ValueError('Source database does not exist')
    if source == destination or destination.exists():
        raise ValueError('Choose a new backup path')
    with destination.open('xb'):
        pass
    try:
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src:
            with closing(sqlite3.connect(destination)) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Backup integrity check failed')
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('--apply', action='store_true', help='Apply after making the required backup')
    parser.add_argument('--backup', type=Path)
    args = parser.parse_args()
    if args.apply and not args.backup:
        parser.error('--apply requires a new --backup path; stop writers first')
    if args.apply:
        backup_database(args.database, args.backup)
        with closing(sqlite3.connect(args.database)) as con:
            con.execute('PRAGMA foreign_keys=ON')
            print('Applied migrations:', migrate(con))
    else:
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / 'dry-run.sqlite3'
            backup_database(args.database, copy)
            with closing(sqlite3.connect(copy)) as con:
                con.execute('PRAGMA foreign_keys=ON')
                print('Dry-run migrations:', migrate(con))
                if con.execute('PRAGMA foreign_key_check').fetchall():
                    raise RuntimeError('Foreign-key check failed')
                print('Integrity:', con.execute('PRAGMA integrity_check').fetchone()[0])


if __name__ == '__main__':
    main()
