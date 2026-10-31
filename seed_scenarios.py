"""Build an isolated, offline TEST dataset for manual inspection."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from seed_test_data import check_fixture_file, fixture_directory, fixture_id, seed


SCENARIO = 'momiq-care-demo-v1'


def populate(directory, current):
    import booking_care
    import booking_chat
    import booking_engine as engine
    import catalog
    import conversations
    import server
    import wallet

    customer, sitter, pet = (fixture_id(name) for name in ('customer', 'boarding', 'cat'))
    with sqlite3.connect(directory / 'momiq.sqlite3', factory=server.ClosingConnection) as con:
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        account = json.loads(con.execute('SELECT account FROM users WHERE id=?', (sitter,)).fetchone()[0])
        photo = account['pets'][0]['photo']
        account['profile']['photo'] = photo
        account['sitterProfile']['homePhotos'] = [photo]
        con.execute('UPDATE users SET account=? WHERE id=?', (json.dumps(account), sitter))
        wallet.post_entry(con, sitter, 100000000, 'topup', SCENARIO, 'fixture', 'TEST opening balance')
        con.commit()
        catalog.review(con, sitter, 'boarding', {'decision': 'approve', 'reason': 'TEST scenario',
                       'testOnly': True, '_revision': catalog.revision(con, sitter)}, 'fixture', 'test')
        con.commit()

        for status, offset in [('active', -1), ('pending', 3), ('rejected', 4)]:
            start = current + timedelta(days=offset)
            requested = min(current, start - timedelta(days=1))
            quote = engine.prepare_quote(con, customer, sitter + ':boarding', [pet], start.isoformat(),
                                         (start + timedelta(days=2)).isoformat(), policy=engine.DailyPolicy(),
                                         environment='test', now=requested)
            con.commit()
            booking = engine.request_booking(con, customer, quote['id'], fixture_id(status),
                                             environment='test', now=requested)
            con.commit()
            if status == 'pending':
                continue
            action = 'accept' if status == 'active' else 'reject'
            identity = booking['id']
            booking = engine.act(con, sitter, identity, action, booking['revision'], fixture_id(action),
                                 reason='TEST scenario', environment='test', now=requested)
            con.commit()
            if status == 'rejected':
                continue
            for actor in (customer, sitter):
                booking = engine.act(con, actor, identity, 'start', booking['revision'], fixture_id('start-' + actor),
                                     environment='test', now=start)
                con.commit()
            chat = booking_chat.open_chat(con, identity, customer, 'test')
            con.commit()
            conversations.send(con, customer, chat['id'], {'requestId': fixture_id('message'),
                               'text': 'TEST — mushuk ovqatlandimi?'}, server.validate_photo)
            con.commit()
            booking_care.save(con, identity, sitter, {
                'kind': 'report', 'category': 'food', 'day': booking_care.today(current), 'petId': pet,
                'requestId': fixture_id('report'), 'revision': 0,
                'payload': {'state': 'done', 'note': 'TEST — mushuk ovqatlandi.'}}, current)
            con.commit()
        if con.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or con.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Invalid scenario database')
        con.execute('INSERT INTO runtime_metadata(key,value) VALUES(?,?)', ('fixture_scenario', SCENARIO))


def build(directory):
    if os.environ.get('MOMIQ_ENV', 'local') not in ('local', 'test'):
        raise ValueError('Scenario fixtures require a local/test runtime')
    target = fixture_directory(directory)
    if target.exists():
        database = target / 'momiq.sqlite3'
        for name in ('momiq.sqlite3', 'momiq.sqlite3-wal', 'momiq.sqlite3-shm', 'momiq.sqlite3-journal'):
            check_fixture_file(target / name)
        if database.is_file():
            from contextlib import closing
            with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as con:
                labels = dict(con.execute("SELECT key,value FROM runtime_metadata WHERE key IN ('environment','fixture_scenario')"))
                if labels == {'environment': 'test', 'fixture_scenario': SCENARIO}:
                    return 'already-created'
        raise ValueError('Scenario requires a new directory')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as temporary:
        staged = Path(temporary) / 'dataset'
        seed(staged, 'test')
        populate(staged, datetime.now(timezone.utc).replace(microsecond=0))
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
