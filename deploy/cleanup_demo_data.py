"""One-time removal of known demo records. Makes a verified backup first."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import argparse

DEMO_SITTERS = {'hoji', 'nilufar', 'aziz', 'sitora', 'malika'}

def clean(con):
    placeholders = ','.join('?' for _ in DEMO_SITTERS)
    # These IDs were exclusively hardcoded demonstration contacts.
    messages = con.execute(f'DELETE FROM messages WHERE sitter IN ({placeholders})', tuple(DEMO_SITTERS)).rowcount
    removed = 0
    for uid, phone, raw in con.execute('SELECT id,phone,account FROM users').fetchall():
        account = json.loads(raw)
        profile = account.get('profile', {})
        signature = (profile.get('first'), profile.get('last'))
        if phone == '998900000001' and signature in [('Sinov', 'Mijoz'), ('Deploy', 'Test')]:
            con.execute('DELETE FROM messages WHERE user_id=?', (uid,))
            con.execute("DELETE FROM sessions WHERE user_id=? AND role='client'", (uid,))
            con.execute('DELETE FROM users WHERE id=?', (uid,))
            removed += 1
        else:
            account['favorites'] = [v for v in account.get('favorites', []) if v not in DEMO_SITTERS]
            con.execute('UPDATE users SET account=? WHERE id=?', (json.dumps(account), uid))
    return messages, removed

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('database', type=Path)
    parser.add_argument('backup_dir', type=Path)
    args = parser.parse_args()
    if not args.database.is_file(): raise SystemExit('Database does not exist')
    args.backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = args.backup_dir / ('before-demo-cleanup-' + stamp + '.sqlite3')
    with sqlite3.connect(args.database) as con:
        with sqlite3.connect(backup) as target:
            con.backup(target)
            assert target.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        backup.chmod(0o600)
        messages, users = clean(con)
        assert con.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    print(f'Demo messages removed: {messages}; deployment test accounts removed: {users}; backup verified')
