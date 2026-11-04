"""Replay committed TEST notifications into an offline simulated push provider."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3

from seed_scenarios import SCENARIO
from seed_test_data import check_fixture_file, fixture_directory, fixture_id

_PROVIDER_ID = 0x4D505348  # MPSH, the local push simulator
_TABLES = {
    'progress':'CREATE TABLE progress(owner TEXT PRIMARY KEY,acked INTEGER NOT NULL)',
    'received':'''CREATE TABLE received(owner TEXT NOT NULL,notice INTEGER NOT NULL,
                    payload TEXT NOT NULL,PRIMARY KEY(owner,notice))''',
}


def prepare_provider(db):
    # Existing unmarked simulators used these exact two tables. Never add
    # simulator tables to another database placed in the fixture directory.
    with db:
        db.execute('BEGIN IMMEDIATE')
        identity=db.execute('PRAGMA application_id').fetchone()[0]
        objects=dict(db.execute("SELECT name,sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'"))
        if identity not in (0,_PROVIDER_ID) or db.execute('PRAGMA user_version').fetchone()[0]!=0:
            raise ValueError('Foreign push simulator database')
        if not objects and identity==0 and db.execute('PRAGMA schema_version').fetchone()[0]==0:
            for statement in _TABLES.values():
                db.execute(statement)
        elif objects!=_TABLES:
            raise ValueError('Unexpected push simulator schema')
        if identity==0:
            db.execute(f'PRAGMA application_id={_PROVIDER_ID}')


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
        owner = app.execute("SELECT blocked,json_extract(account,'$.notifications') FROM users WHERE id=?",(uid,)).fetchone()
        if owner is None:
            raise ValueError('TEST recipient missing')
        blocked,raw_preferences = owner
        preferences = json.loads(raw_preferences) if raw_preferences else {}
        if not isinstance(preferences,dict):
            raise ValueError('Invalid notification preferences')
        # Simulate the consumer cursor and the provider's independent acceptance
        # record. Never attach either to the business transaction or a real device.
        with closing(sqlite3.connect(root/'push-sandbox.sqlite3')) as db:
            prepare_provider(db)
            cursor = db.execute('SELECT acked FROM progress WHERE owner=?',(uid,)).fetchone()
            rows = app.execute("""SELECT id,json_extract(payload,'$.kind'),json_extract(payload,'$.status')
                               FROM notifications WHERE user_id=? AND id>? ORDER BY id LIMIT ?""",
                               (uid, cursor[0] if cursor else 0, limit))
            stats = {'accepted':0, 'duplicate':0, 'acknowledged':0, 'suppressed':0, 'retryPending':False}
            for identity,kind,status in rows:
                category = {'conversation':'chat','booking':'orders'}.get(kind)
                if kind=='care' and status in ('video','video_reminder','video_missing','video_explanation'):
                    category='video'
                suppressed = blocked or (category is not None and preferences.get(category,True) is not True)
                if suppressed:
                    stats['suppressed'] += 1
                elif outcome == 'unavailable':
                    stats['retryPending'] = True
                    break
                else:
                    # Only a generic alert and owner-authenticated notice ID leave the app DB.
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
                if not suppressed:
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
