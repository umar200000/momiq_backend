"""Explicit fixtures for a NEW, marked local/test database. Never run on live data.

python seed_test_data.py --data-dir .local/preview
python seed_test_data.py --data-dir .local/preview --clean
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3

MARKER = '.momiq-test-fixtures.json'
FIXTURE_VERSION = 1
OWNER = 'momiq-preview-v1'


def fixture_id(name):
    return hashlib.sha256((OWNER + ':' + name).encode()).hexdigest()[:24]


def prepare_directory(directory, mode):
    directory = Path(directory).resolve()
    if mode not in {'local', 'test'}:
        raise ValueError('Fixtures are only allowed in local/test, not hosted environments')
    marker = directory / MARKER
    if marker.exists():
        if json.loads(marker.read_text(encoding='utf-8')) != {'owner': OWNER, 'version': FIXTURE_VERSION}:
            raise ValueError('Unknown fixture marker')
    else:
        if directory.exists() and any(directory.iterdir()):
            raise ValueError('Refusing to seed or adopt a non-empty, unmarked directory')
        directory.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({'owner': OWNER, 'version': FIXTURE_VERSION}), encoding='utf-8')
    return directory


def seed(directory, mode='local', clean=False):
    # Import after environment checks; the command must never open production data.
    if os.environ.get('MOMIQ_ENV', 'local') not in {'local', 'test'}:
        raise ValueError('Refusing fixture operations from a hosted runtime')
    if clean and not (Path(directory) / MARKER).is_file():
        raise ValueError('Cleanup requires an existing fixture marker')
    directory = prepare_directory(directory, mode)
    import server
    from unittest.mock import patch
    with patch.object(server, 'DATA', directory), patch.object(server, 'ENVIRONMENT', mode):
        server.setup()
        names = ['customer', 'boarding', 'homeVisit', 'personal']
        ids = [fixture_id(n) for n in names]
        photo = base64.b64encode(bytes.fromhex(
            '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489'
            '0000000b49444154789c6360000200000500017a5eab3f0000000049454e44ae426082')).decode()
        with server.db() as con:
            con.execute('BEGIN IMMEDIATE')
            if clean:
                references = set(ids) | {uid+':'+service for uid in ids for service in ('boarding','homeVisit','personal')}
                for uid in ids:
                    if con.execute('SELECT 1 FROM support_tickets WHERE owner_id=? LIMIT 1', (uid,)).fetchone():
                        raise ValueError('Fixture has support history; cleanup refused. Use a new isolated preview directory.')
                    if con.execute('SELECT 1 FROM chat_blocks WHERE blocker_id=? OR blocked_id=? LIMIT 1', (uid,uid)).fetchone():
                        raise ValueError('Fixture has contact-block history; cleanup refused. Use a new isolated preview directory.')
                    if con.execute('SELECT 1 FROM conversations WHERE customer_id=? OR sitter_id=? LIMIT 1',(uid,uid)).fetchone():
                        raise ValueError('Fixture has conversation history; cleanup refused. Use a new isolated preview directory.')
                    if con.execute('SELECT 1 FROM booking_quotes WHERE customer_id=? OR sitter_id=? LIMIT 1',(uid,uid)).fetchone():
                        raise ValueError('Fixture has booking history; cleanup refused. Use a new isolated preview directory.')
                    if con.execute('SELECT 1 FROM topup_requests WHERE user_id=? LIMIT 1',(uid,)).fetchone() or con.execute('SELECT 1 FROM wallet_entries WHERE user_id=? LIMIT 1',(uid,)).fetchone():
                        raise ValueError('Fixture has financial history; cleanup refused. Use a new isolated preview directory.')
                for row in con.execute('SELECT id,account FROM users'):
                    if row['id'] not in ids and set(json.loads(row['account']).get('favorites', [])) & references:
                        raise ValueError('Unowned account references fixtures; cleanup refused')
                for row in con.execute('SELECT user_id,sitter FROM messages'):
                    if row['user_id'] not in ids and row['sitter'] in references:
                        raise ValueError('Unowned conversation references fixtures; cleanup refused')
                for uid in ids:
                    con.execute('DELETE FROM messages WHERE user_id=?', (uid,))
                    con.execute('DELETE FROM notifications WHERE user_id=?', (uid,))
                    con.execute('DELETE FROM sessions WHERE user_id=?', (uid,))
                    con.execute('DELETE FROM wallet_accounts WHERE user_id=? AND balance_minor=0', (uid,))
                    con.execute('DELETE FROM users WHERE id=?', (uid,))
                    con.execute('DELETE FROM sitters WHERE id=?', (uid,))
                return {'cleaned': len(ids), 'directory': str(directory)}
            for i, (name, uid) in enumerate(zip(names, ids), 1):
                account = server.default_account()
                account['profile'] = {'first': 'TEST', 'last': name, 'photo': None}
                account['pets'] = [{'id': fixture_id('cat'), 'type': 'Mushuk', 'name': 'Test Momi', 'photo': photo}]
                role = 'customer' if i == 1 else 'sitter'
                if role == 'sitter':
                    account['sitterProfile'] = {'housing': 'house', 'years': 1,
                                               'about': 'TEST — haqiqiy xizmat emas', 'homePhotos': []}
                # Never overwrite a fixture that a tester has edited.
                con.execute('INSERT INTO users VALUES(?,?,?,0,?) ON CONFLICT(id) DO NOTHING',
                            (uid, f'99800000000{i}', json.dumps(account), server.now()))
                con.execute('INSERT OR IGNORE INTO user_roles VALUES(?,?)', (uid, role))
                if role == 'customer':
                    continue
                location = {'lat': 41.3111, 'lon': 69.2797, 'address': 'TEST — Toshkent, haqiqiy topshirish manzili emas'}
                listing = server.validate_listings({'housing': 'house', 'listings': [{
                    'type': name, 'pets': ['cat'], 'price': 100000 * (i - 1),
                    'capacity': 3 if name == 'boarding' else None,
                    'location': None if name == 'homeVisit' else location, 'active': True}]})
                con.execute('INSERT INTO listings VALUES(?,?,?) ON CONFLICT(user_id) DO NOTHING',
                            (uid, json.dumps(listing), server.now()))
                profile = {'name': 'TEST ' + name, 'service': i - 2, 'price': 100000 * (i - 1),
                           'pets': ['Mushuk'], 'capacity': 1 if name == 'personal' else 3,
                           'occupied': 0, 'rating': 0, 'reviews': 0, 'years': 1, 'distance': 0,
                           'about': 'TEST — haqiqiy enaga emas', 'photo': photo, 'homePhotos': [],
                           'location': location, 'testOnly': True}
                con.execute('INSERT INTO sitters VALUES(?,?,1) ON CONFLICT(id) DO NOTHING', (uid, json.dumps(profile)))
            return {'accounts': len(ids), 'directory': str(directory), 'phones': [f'99800000000{i}' for i in range(1, 5)]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--environment', choices=['local', 'test'], default='local')
    parser.add_argument('--clean', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(seed(args.data_dir, args.environment, args.clean), ensure_ascii=False))
    except (ValueError, sqlite3.Error) as error:
        parser.exit(1, f'{error}\n')
