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
    (7, 'versioned top-up clarification and evidence history', (
        'ALTER TABLE topup_requests RENAME TO topup_requests_legacy_v7',
        'DROP INDEX topup_requests_status',
        "CREATE TABLE topup_requests(id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), amount_minor INTEGER NOT NULL CHECK(amount_minor > 0), receipt TEXT NOT NULL, receipt_hash TEXT NOT NULL UNIQUE, qr_version INTEGER NOT NULL REFERENCES platform_settings(version), terms_version TEXT NOT NULL, request_id TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','needs_info')), transfer_reference TEXT UNIQUE, reviewed_by TEXT, review_reason TEXT, created TEXT NOT NULL, reviewed_at TEXT, payer_reference TEXT NOT NULL DEFAULT '', paid_at TEXT, revision INTEGER NOT NULL DEFAULT 0 CHECK(revision>=0), UNIQUE(user_id,request_id))",
        'INSERT INTO topup_requests(id,user_id,amount_minor,receipt,receipt_hash,qr_version,terms_version,request_id,status,transfer_reference,reviewed_by,review_reason,created,reviewed_at,payer_reference,paid_at) SELECT id,user_id,amount_minor,receipt,receipt_hash,qr_version,terms_version,request_id,status,transfer_reference,reviewed_by,review_reason,created,reviewed_at,payer_reference,paid_at FROM topup_requests_legacy_v7',
        'DROP TABLE topup_requests_legacy_v7',
        'CREATE INDEX topup_requests_status ON topup_requests(status,created,id)',
        'CREATE TABLE topup_evidence_claims(receipt_hash TEXT PRIMARY KEY, topup_id TEXT NOT NULL REFERENCES topup_requests(id), receipt TEXT NOT NULL)',
        'INSERT INTO topup_evidence_claims SELECT receipt_hash,id,receipt FROM topup_requests',
        'CREATE TABLE topup_history(topup_id TEXT NOT NULL REFERENCES topup_requests(id), revision INTEGER NOT NULL, event TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL, created TEXT NOT NULL, amount_minor INTEGER NOT NULL, receipt_hash TEXT NOT NULL, qr_version INTEGER NOT NULL, terms_version TEXT NOT NULL, payer_reference TEXT NOT NULL, paid_at TEXT, status TEXT NOT NULL, request_id TEXT, PRIMARY KEY(topup_id,revision), UNIQUE(topup_id,request_id))',
        "INSERT INTO topup_history SELECT id,0,'migrated','system','Existing evidence imported; earlier transitions are not reconstructed',strftime('%Y-%m-%dT%H:%M:%fZ','now'),amount_minor,receipt_hash,qr_version,terms_version,payer_reference,paid_at,status,NULL FROM topup_requests",
        "CREATE TRIGGER topup_history_no_update BEFORE UPDATE ON topup_history BEGIN SELECT RAISE(ABORT, 'Top-up history is immutable'); END",
        "CREATE TRIGGER topup_history_no_delete BEFORE DELETE ON topup_history BEGIN SELECT RAISE(ABORT, 'Top-up history is immutable'); END",
        "CREATE TRIGGER topup_claims_no_update BEFORE UPDATE ON topup_evidence_claims BEGIN SELECT RAISE(ABORT, 'Receipt claim is immutable'); END",
        "CREATE TRIGGER topup_claims_no_delete BEFORE DELETE ON topup_evidence_claims BEGIN SELECT RAISE(ABORT, 'Receipt claim is immutable'); END",
    )),
    (8, 'participant scoped conversations and ordered messages', (
        "CREATE TABLE conversations(seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, customer_id TEXT NOT NULL REFERENCES users(id), sitter_id TEXT NOT NULL REFERENCES users(id), service TEXT NOT NULL CHECK(service IN ('boarding','homeVisit','personal')), customer_name TEXT NOT NULL, sitter_name TEXT NOT NULL, created TEXT NOT NULL, CHECK(customer_id!=sitter_id), UNIQUE(customer_id,sitter_id,service))",
        'CREATE INDEX conversations_customer ON conversations(customer_id,seq)',
        'CREATE INDEX conversations_sitter ON conversations(sitter_id,seq)',
        "CREATE TABLE conversation_messages(id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL REFERENCES conversations(id), sender_id TEXT NOT NULL REFERENCES users(id), sender_role TEXT NOT NULL CHECK(sender_role IN ('customer','sitter')), text TEXT NOT NULL, image TEXT, request_id TEXT NOT NULL, created TEXT NOT NULL, UNIQUE(sender_id,request_id))",
        'CREATE INDEX conversation_messages_page ON conversation_messages(conversation_id,id)',
        'CREATE TABLE conversation_reads(conversation_id TEXT NOT NULL REFERENCES conversations(id), user_id TEXT NOT NULL REFERENCES users(id), last_message_id INTEGER NOT NULL DEFAULT 0 CHECK(last_message_id>=0), PRIMARY KEY(conversation_id,user_id))',
    )),
    (9, 'chat blocks reports and redaction events', (
        'CREATE TABLE chat_blocks(blocker_id TEXT NOT NULL REFERENCES users(id), blocked_id TEXT NOT NULL REFERENCES users(id), active INTEGER NOT NULL CHECK(active IN (0,1)), revision INTEGER NOT NULL, updated TEXT NOT NULL, PRIMARY KEY(blocker_id,blocked_id), CHECK(blocker_id!=blocked_id))',
        'ALTER TABLE conversation_messages ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0 CHECK(hidden IN (0,1))',
        'CREATE TABLE chat_changes(id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL REFERENCES conversations(id), message_id INTEGER NOT NULL UNIQUE REFERENCES conversation_messages(id), created TEXT NOT NULL)',
        'CREATE INDEX chat_changes_page ON chat_changes(conversation_id,id)',
        "CREATE TABLE chat_reports(id INTEGER PRIMARY KEY AUTOINCREMENT, reporter_id TEXT NOT NULL REFERENCES users(id), message_id INTEGER NOT NULL REFERENCES conversation_messages(id), request_id TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('open','dismissed','removed')), revision INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL, reviewed_at TEXT, reviewed_by TEXT, review_reason TEXT, UNIQUE(reporter_id,request_id), UNIQUE(reporter_id,message_id))",
        'CREATE INDEX chat_reports_queue ON chat_reports(status,id)',
        'CREATE TABLE chat_report_history(report_id INTEGER NOT NULL REFERENCES chat_reports(id), revision INTEGER NOT NULL, status TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(report_id,revision))',
        "CREATE TRIGGER chat_report_history_no_update BEFORE UPDATE ON chat_report_history BEGIN SELECT RAISE(ABORT, 'Chat review history is immutable'); END",
        "CREATE TRIGGER chat_report_history_no_delete BEFORE DELETE ON chat_report_history BEGIN SELECT RAISE(ABORT, 'Chat review history is immutable'); END",
    )),
    (10, 'immutable booking quotes and transactional reservations', (
        'CREATE TABLE booking_quotes(id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES users(id), sitter_id TEXT NOT NULL REFERENCES users(id), service TEXT NOT NULL, snapshot TEXT NOT NULL, created TEXT NOT NULL, expires_at TEXT NOT NULL, test_only INTEGER NOT NULL CHECK(test_only=1))',
        "CREATE TRIGGER booking_quotes_no_update BEFORE UPDATE ON booking_quotes BEGIN SELECT RAISE(ABORT, 'Booking quote is immutable'); END",
        "CREATE TRIGGER booking_quotes_no_delete BEFORE DELETE ON booking_quotes BEGIN SELECT RAISE(ABORT, 'Booking quote is immutable'); END",
        "CREATE TABLE bookings(seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, quote_id TEXT NOT NULL UNIQUE REFERENCES booking_quotes(id), customer_id TEXT NOT NULL REFERENCES users(id), sitter_id TEXT NOT NULL REFERENCES users(id), service TEXT NOT NULL CHECK(service IN ('boarding','homeVisit','personal')), starts_at TEXT NOT NULL, ends_at TEXT NOT NULL, reply_deadline TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('pending','accepted','rejected','expired','cancelled','active','completed','disputed')), revision INTEGER NOT NULL DEFAULT 0 CHECK(revision>=0), created TEXT NOT NULL, updated TEXT NOT NULL, CHECK(customer_id!=sitter_id), CHECK(starts_at<ends_at))",
        'CREATE INDEX bookings_customer ON bookings(customer_id,seq)',
        'CREATE INDEX bookings_sitter ON bookings(sitter_id,status,starts_at,ends_at)',
        "CREATE INDEX bookings_due ON bookings(reply_deadline) WHERE status='pending'",
        'CREATE TABLE booking_animals(booking_id TEXT NOT NULL REFERENCES bookings(id), customer_id TEXT NOT NULL REFERENCES users(id), animal_id TEXT NOT NULL, PRIMARY KEY(booking_id,animal_id))',
        'CREATE INDEX booking_animals_owner ON booking_animals(customer_id,animal_id)',
        "CREATE TRIGGER booking_animals_no_update BEFORE UPDATE ON booking_animals BEGIN SELECT RAISE(ABORT, 'Booking animals are immutable'); END",
        "CREATE TRIGGER booking_animals_no_delete BEFORE DELETE ON booking_animals BEGIN SELECT RAISE(ABORT, 'Booking animals are immutable'); END",
        'CREATE TABLE booking_events(booking_id TEXT NOT NULL REFERENCES bookings(id), revision INTEGER NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(booking_id,revision))',
        "CREATE TRIGGER booking_events_no_update BEFORE UPDATE ON booking_events BEGIN SELECT RAISE(ABORT, 'Booking history is immutable'); END",
        "CREATE TRIGGER booking_events_no_delete BEFORE DELETE ON booking_events BEGIN SELECT RAISE(ABORT, 'Booking history is immutable'); END",
        'CREATE TABLE booking_requests(actor TEXT NOT NULL REFERENCES users(id), request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, booking_id TEXT NOT NULL REFERENCES bookings(id), PRIMARY KEY(actor,request_id))',
        "CREATE TRIGGER booking_identity_immutable BEFORE UPDATE OF quote_id,customer_id,sitter_id,service,starts_at,ends_at,reply_deadline,created ON bookings BEGIN SELECT RAISE(ABORT, 'Booking agreement is immutable'); END",
    )),
    (11, 'private content-addressed booking animal evidence', (
        'CREATE TABLE booking_media(hash TEXT PRIMARY KEY, image TEXT NOT NULL)',
        "CREATE TABLE booking_quote_media(quote_id TEXT NOT NULL REFERENCES booking_quotes(id), animal_id TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('photo','passport')), media_hash TEXT NOT NULL REFERENCES booking_media(hash), PRIMARY KEY(quote_id,animal_id,kind))",
        "CREATE TRIGGER booking_media_no_update BEFORE UPDATE ON booking_media BEGIN SELECT RAISE(ABORT, 'Booking evidence is immutable'); END",
        "CREATE TRIGGER booking_media_no_delete BEFORE DELETE ON booking_media BEGIN SELECT RAISE(ABORT, 'Booking evidence is immutable'); END",
        "CREATE TRIGGER booking_quote_media_no_update BEFORE UPDATE ON booking_quote_media BEGIN SELECT RAISE(ABORT, 'Booking evidence reference is immutable'); END",
        "CREATE TRIGGER booking_quote_media_no_delete BEFORE DELETE ON booking_quote_media BEGIN SELECT RAISE(ABORT, 'Booking evidence reference is immutable'); END",
    )),
    (12, 'immutable platform settings history', (
        "CREATE TRIGGER platform_settings_no_update BEFORE UPDATE ON platform_settings BEGIN SELECT RAISE(ABORT, 'Platform settings history is immutable'); END",
        "CREATE TRIGGER platform_settings_no_delete BEFORE DELETE ON platform_settings BEGIN SELECT RAISE(ABORT, 'Platform settings history is immutable'); END",
    )),
    (13, 'participant delivery acknowledgements', (
        'CREATE TABLE conversation_deliveries(conversation_id TEXT NOT NULL REFERENCES conversations(id), user_id TEXT NOT NULL REFERENCES users(id), last_message_id INTEGER NOT NULL CHECK(last_message_id>0), PRIMARY KEY(conversation_id,user_id))',
    )),
    (14, 'immutable booking care instructions and daily reports', (
        "CREATE TABLE care_entries(id INTEGER PRIMARY KEY AUTOINCREMENT, booking_id TEXT NOT NULL REFERENCES bookings(id), pet_id TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('instructions','report')), day TEXT NOT NULL, category TEXT NOT NULL, revision INTEGER NOT NULL, actor TEXT NOT NULL REFERENCES users(id), request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL, created TEXT NOT NULL, UNIQUE(actor,request_id), UNIQUE(booking_id,pet_id,kind,day,category,revision))",
        'CREATE INDEX care_lookup ON care_entries(booking_id,kind,day,pet_id,category,revision)',
        "CREATE TRIGGER care_entries_no_update BEFORE UPDATE ON care_entries BEGIN SELECT RAISE(ABORT, 'Care history is immutable'); END",
        "CREATE TRIGGER care_entries_no_delete BEFORE DELETE ON care_entries BEGIN SELECT RAISE(ABORT, 'Care history is immutable'); END",
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
