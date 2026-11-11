"""Create a NEW isolated local MVP catalog: TEST accounts/balances, no bookings."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from seed_test_data import check_fixture_file, fixture_directory, fixture_id, seed

SCENARIO = 'momiq-mvp-catalog-v1'


def populate(directory):
    import catalog
    import server
    import wallet

    with sqlite3.connect(directory / 'momiq.sqlite3', factory=server.ClosingConnection) as con:
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        for service in ('boarding', 'homeVisit', 'personal'):
            uid = fixture_id(service)
            account = json.loads(con.execute('SELECT account FROM users WHERE id=?', (uid,)).fetchone()[0])
            photo = account['pets'][0]['photo']
            account['profile']['photo'] = photo
            account['sitterProfile']['homePhotos'] = [photo]
            con.execute('UPDATE users SET account=? WHERE id=?', (json.dumps(account), uid))
            wallet.post_entry(con, uid, 100000000, 'topup', SCENARIO + ':' + service, 'TEST fixture',
                              'TEST synthetic opening balance; no payment received')
            con.commit()
            catalog.review(con, uid, service, {'decision': 'approve', 'reason': 'TEST MVP; not MyID',
                           'testOnly': True, '_revision': catalog.revision(con, uid)}, 'TEST fixture', 'local')
            con.commit()
        if len(list(catalog.profiles(con, 'local'))) != 3:
            raise ValueError('Expected all three TEST services in local catalog')
        if list(catalog.profiles(con, 'production')):
            raise ValueError('TEST catalog must not be production eligible')
        if con.execute('SELECT COUNT(*) FROM bookings').fetchone()[0]:
            raise ValueError('MVP catalog must not create bookings')
        if con.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or con.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Invalid MVP database')
        con.execute('INSERT INTO runtime_metadata(key,value) VALUES(?,?)', ('fixture_mvp', SCENARIO))


def build(directory):
    if os.environ.get('MOMIQ_ENV', 'local') not in ('local', 'test'):
        raise ValueError('MVP fixtures require a local/test runtime')
    target = fixture_directory(directory)
    if target.exists():
        for name in ('momiq.sqlite3', 'momiq.sqlite3-wal', 'momiq.sqlite3-shm', 'momiq.sqlite3-journal'):
            check_fixture_file(target / name)
        database = target / 'momiq.sqlite3'
        if database.is_file():
            with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as con:
                labels = dict(con.execute("SELECT key,value FROM runtime_metadata WHERE key IN ('environment','fixture_mvp')"))
                if labels == {'environment': 'local', 'fixture_mvp': SCENARIO}:
                    return 'already-created'
        raise ValueError('MVP fixtures require a new directory')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as temporary:
        staged = Path(temporary) / 'dataset'
        seed(staged, 'local')
        populate(staged)
        staged.rename(target)
    return 'created'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', required=True)
    args = parser.parse_args()
    try:
        print(build(args.data_dir))
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, f'{error}\n')
