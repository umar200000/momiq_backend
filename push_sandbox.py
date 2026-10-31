"""Replay committed TEST notifications into an offline simulated push provider."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3

from seed_scenarios import SCENARIO
from seed_test_data import check_fixture_file, fixture_directory, fixture_id


def replay(directory, account, outcome='accepted', limit=20):
    if (os.environ.get('MOMIQ_ENV','local') not in ('local','test') or
            account not in ('customer','boarding','personal','homeVisit') or
            outcome not in ('accepted','unavailable','lost-response') or not 1 <= limit <= 100):
        raise ValueError('Invalid sandbox invocation')
    root = fixture_directory(directory)
    for filename in ('momiq.sqlite3','push-sandbox.sqlite3'):
        for suffix in ('','-shm','-wal','-journal'):
            check_fixture_file(root/(filename+suffix))
    uid = fixture_id(account)
    with closing(sqlite3.connect((root/'momiq.sqlite3').as_uri()+'?mode=ro',uri=True)) as app:
        app.execute('BEGIN')
        labels = dict(app.execute("SELECT key,value FROM runtime_metadata WHERE key IN ('environment','fixture_scenario')"))
        if labels != {'environment':'test','fixture_scenario':SCENARIO}:
            raise ValueError('Only the offline TEST scenario can receive synthetic push')
        # Simulate the consumer cursor and the provider's independent acceptance
        # record. Never attach either to the business transaction or a real device.
        with closing(sqlite3.connect(root/'push-sandbox.sqlite3')) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS progress(owner TEXT PRIMARY KEY,acked INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS received(owner TEXT NOT NULL,notice INTEGER NOT NULL,
                    payload TEXT NOT NULL,PRIMARY KEY(owner,notice));
            """)
            cursor = db.execute('SELECT acked FROM progress WHERE owner=?',(uid,)).fetchone()
            rows = app.execute('SELECT id FROM notifications WHERE user_id=? AND id>? ORDER BY id LIMIT ?',
                               (uid, cursor[0] if cursor else 0, limit))
            stats = {'accepted':0, 'duplicate':0, 'acknowledged':0, 'retryPending':False}
            for (identity,) in rows:
                if outcome == 'unavailable':
                    stats['retryPending'] = True
                    break
                # Private text, actor, address, type and financial details never
                # leave the app database. The ID opens owner-authenticated history.
                message = json.dumps({'noticeId':str(identity),'title':'Momiq','body':'Yangi bildirishnoma'})
                with db:
                    inserted = db.execute('INSERT OR IGNORE INTO received VALUES(?,?,?)',
                                          (uid,identity,message)).rowcount
                stats['accepted' if inserted else 'duplicate'] += 1
                if outcome == 'lost-response':
                    stats['retryPending'] = True
                    break
                with db:
                    db.execute('INSERT INTO progress VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET acked=MAX(acked,excluded.acked)',
                               (uid,identity))
                stats['acknowledged'] += 1
            return stats


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',required=True)
    parser.add_argument('--account',required=True,choices=('customer','boarding','personal','homeVisit'))
    parser.add_argument('--outcome',choices=('accepted','unavailable','lost-response'),default='accepted')
    args = parser.parse_args()
    try:
        print(json.dumps(replay(args.data_dir,args.account,args.outcome)))
    except (OSError,sqlite3.Error,ValueError):
        parser.exit(1,'Offline push replay failed\n')
