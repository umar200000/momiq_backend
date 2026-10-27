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
    (2, 'manual wallet and payment evidence', (
        'CREATE TABLE wallet_accounts(user_id TEXT PRIMARY KEY REFERENCES users(id), balance_minor INTEGER NOT NULL DEFAULT 0 CHECK(balance_minor >= 0))',
        "CREATE TABLE wallet_entries(id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES wallet_accounts(user_id), amount_minor INTEGER NOT NULL CHECK(amount_minor != 0), balance_after INTEGER NOT NULL CHECK(balance_after >= 0), kind TEXT NOT NULL, source_key TEXT NOT NULL UNIQUE, actor TEXT NOT NULL, reason TEXT NOT NULL, created TEXT NOT NULL)",
        'CREATE INDEX wallet_entries_user ON wallet_entries(user_id,created,id)',
        "CREATE TRIGGER wallet_entries_no_update BEFORE UPDATE ON wallet_entries BEGIN SELECT RAISE(ABORT, 'Wallet journal is immutable'); END",
        "CREATE TRIGGER wallet_entries_no_delete BEFORE DELETE ON wallet_entries BEGIN SELECT RAISE(ABORT, 'Wallet journal is immutable'); END",
        'CREATE TABLE platform_settings(version INTEGER PRIMARY KEY AUTOINCREMENT, commission_bps INTEGER NOT NULL CHECK(commission_bps BETWEEN 0 AND 10000), qr_image TEXT, test_only INTEGER NOT NULL CHECK(test_only IN (0,1)), actor TEXT NOT NULL, reason TEXT NOT NULL, created TEXT NOT NULL)',
        "INSERT INTO platform_settings(commission_bps,qr_image,test_only,actor,reason,created) VALUES(1000,NULL,0,'system','Initial 10 percent commission',CURRENT_TIMESTAMP)",
        "CREATE TABLE topup_requests(id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), amount_minor INTEGER NOT NULL CHECK(amount_minor > 0), receipt TEXT NOT NULL, receipt_hash TEXT NOT NULL UNIQUE, qr_version INTEGER NOT NULL REFERENCES platform_settings(version), terms_version TEXT NOT NULL, request_id TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected')), transfer_reference TEXT UNIQUE, reviewed_by TEXT, review_reason TEXT, created TEXT NOT NULL, reviewed_at TEXT, UNIQUE(user_id,request_id))",
        'CREATE INDEX topup_requests_status ON topup_requests(status,created,id)',
    )),
    (3, 'listing revisions and moderation', (
        'CREATE TABLE listing_revisions(user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0))',
        'INSERT INTO listing_revisions(user_id) SELECT id FROM users',
        "CREATE TABLE listing_moderation(user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, service TEXT NOT NULL CHECK(service IN ('boarding','homeVisit','personal')), status TEXT NOT NULL CHECK(status IN ('draft','pending','approved','rejected','suspended','archived')), approved_hash TEXT, test_only INTEGER NOT NULL DEFAULT 0 CHECK(test_only IN (0,1)), reason TEXT NOT NULL DEFAULT '', reviewed_by TEXT, reviewed_at TEXT, public_media TEXT, PRIMARY KEY(user_id,service))",
    )),
    (4, 'payment recipient and QR availability', (
        "ALTER TABLE platform_settings ADD COLUMN recipient_name TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE platform_settings ADD COLUMN payment_instructions TEXT NOT NULL DEFAULT ''",
        'ALTER TABLE platform_settings ADD COLUMN qr_active INTEGER NOT NULL DEFAULT 0 CHECK(qr_active IN (0,1))',
        'ALTER TABLE platform_settings ADD COLUMN legacy_receipt_allowed INTEGER NOT NULL DEFAULT 0 CHECK(legacy_receipt_allowed IN (0,1))',
        'UPDATE platform_settings SET legacy_receipt_allowed=1 WHERE qr_image IS NOT NULL',
    )),
    (5, 'payer supplied payment evidence metadata', (
        "ALTER TABLE topup_requests ADD COLUMN payer_reference TEXT NOT NULL DEFAULT ''",
        'ALTER TABLE topup_requests ADD COLUMN paid_at TEXT',
    )),
    (6, 'transactional in-app notifications', (
        'CREATE TABLE notifications(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL REFERENCES users(id), source_key TEXT NOT NULL UNIQUE, payload TEXT NOT NULL, created TEXT NOT NULL, read_at TEXT)',
        'CREATE INDEX notifications_owner ON notifications(user_id,id)',
        'CREATE INDEX notifications_unread ON notifications(user_id) WHERE read_at IS NULL',
        "CREATE TRIGGER notifications_content_immutable BEFORE UPDATE OF user_id,source_key,payload,created ON notifications BEGIN SELECT RAISE(ABORT, 'Notice content is immutable'); END",
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
