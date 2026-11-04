"""Race real booking transactions on a populated, disposable SQLite database."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import platform
import secrets
import sqlite3
import sys
import tempfile
import threading
import time

from tool.load_test import seed, timings


def run(directory):
    os.environ.update(MOMIQ_DATA_DIR=directory,MOMIQ_ENV='test',MOMIQ_ALLOW_TEST_LOGIN='0')
    import booking_engine as engine
    import catalog
    import server

    if server.DATA.resolve()!=Path(directory).resolve() or server.ENVIRONMENT!='test':
        raise RuntimeError('Isolated TEST instance required')
    server.setup()
    _,sitter_count=seed(server,catalog,1000,100)
    now=datetime.now(timezone.utc)
    start=now+timedelta(days=4)
    end=start+timedelta(hours=24)
    jobs=[]
    for n in range(100):
        owner=f'{sitter_count+n:024x}'
        number=2+3*(n%10)  # ten personal sitters, one place each
        sitter=f'{number:024x}'
        pet={'id':'test-pet','type':'It' if number%2 else 'Mushuk','name':'TEST pet'}
        with server.db() as con:
            con.execute("UPDATE users SET account=json_set(account,'$.pets',json(?)) WHERE id=?",
                        (json.dumps([pet]),owner))
        with server.db() as con:
            quote=engine.prepare_quote(con,owner,sitter+':personal',[pet['id']],start.isoformat(),end.isoformat(),
                                       policy=engine.DailyPolicy(),environment='test',now=now)
        with server.db() as con:
            booking=engine.request_booking(con,owner,quote['id'],secrets.token_hex(16),environment='test',now=now)
        jobs.append((sitter,booking['id'],secrets.token_hex(16)))

    barrier=threading.Barrier(len(jobs),timeout=45)
    def accept(job):
        sitter,identity,key=job
        with server.db() as con:
            barrier.wait()
            started=time.perf_counter()
            try:
                result=engine.act(con,sitter,identity,'accept',0,key,environment='test',now=now)
                con.commit()
                assert result['id']==identity and result['status']=='accepted'
            except engine.BookingError as error:
                con.rollback()
                if error.status!=409 or not error.message.startswith('Tanlangan vaqtda'):
                    raise
                return False,(time.perf_counter()-started)*1000
            return True,(time.perf_counter()-started)*1000

    with ThreadPoolExecutor(len(jobs)) as pool:
        outcomes=list(pool.map(accept,jobs))
    winners=[job for job,(ok,_) in zip(jobs,outcomes) if ok]
    assert len(winners)==len({sitter for sitter,_,_ in winners})==10
    for sitter,identity,key in winners:
        with server.db() as con:
            result=engine.act(con,sitter,identity,'accept',0,key,environment='test',now=now)
            assert result['id']==identity and result['revision']==1
    with server.db() as con:
        states=dict(con.execute('SELECT status,COUNT(*) FROM bookings GROUP BY status'))
        assert states=={'accepted':10,'pending':90}
        accepted_ids={identity for _,identity,_ in winners}
        debits={row[0]:row[1] for row in con.execute("SELECT source_key,amount_minor FROM wallet_entries WHERE kind='commission'")}
        assert debits=={'booking:'+identity+':commission':-500000 for identity in accepted_ids}
        events=[row[0] for row in con.execute("SELECT booking_id FROM booking_events WHERE action='accept'")]
        assert len(events)==10 and set(events)==accepted_ids
        assert not con.execute("""SELECT w.user_id FROM wallet_accounts w LEFT JOIN wallet_entries e
            ON w.user_id=e.user_id GROUP BY w.user_id,w.balance_minor
            HAVING w.balance_minor<>COALESCE(SUM(e.amount_minor),0)""").fetchone()
        assert con.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not con.execute('PRAGMA foreign_key_check').fetchone()
        journal=con.execute('PRAGMA journal_mode').fetchone()[0]
    return dict(accounts=1000,concurrentAccepts=len(jobs),bookingStates=states,replayedAccepts=len(winners),
                commissionEntries=len(debits),acceptEvents=len(events),walletsReconciled=True,integrity='ok',
                foreignKeyErrors=0,transactionLatency=timings([elapsed for _,elapsed in outcomes]),
                sqlite=sqlite3.sqlite_version,journal=journal,platform=platform.system())


if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='momiq-booking-contention-') as tmp:
        report=run(tmp)
    print(json.dumps(report,indent=2))
