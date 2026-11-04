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


def prepare_jobs(directory):
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

    return server, jobs, now


def race_engine(server,jobs,now):
    import booking_engine as engine
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
    return outcomes,winners


def race_http(server,jobs):
    import hashlib
    import http.client
    import subprocess
    from tool.verify_proxy import port, stop

    tokens = {sitter:secrets.token_urlsafe(32) for sitter in {job[0] for job in jobs}}
    with server.db() as con:
        con.executemany('INSERT INTO sessions VALUES(?,?,?,?)', [
            (hashlib.sha256(token.encode()).hexdigest(),sitter,'client',time.time()+600)
            for sitter,token in tokens.items()
        ])
    bind = port()
    process = subprocess.Popen([sys.executable,'-m','gunicorn','--workers','2','--threads','4',
                                '--bind',f'127.0.0.1:{bind}','wsgi:application'],
                               cwd=Path(__file__).resolve().parents[1],stdout=subprocess.DEVNULL)
    def request(path, data=None, token=None):
        conn = http.client.HTTPConnection('127.0.0.1',bind,timeout=45)
        try:
            if data is None:
                conn.request('GET',path)
            else:
                conn.request('POST',path,json.dumps(data),{'Content-Type':'application/json',
                                                          'Authorization':'Bearer '+token})
            response = conn.getresponse()
            return response.status,json.load(response)
        finally:
            conn.close()

    def submit(job):
        sitter,identity,key = job
        status,body = request(f'/api/bookings/{identity}/accept',{'revision':0,'requestId':key},tokens[sitter])
        if status == 409 and body.get('error','').startswith('Tanlangan vaqtda'):
            return False
        assert status == 200, status
        assert body['id']==identity and body['status']=='accepted' and body['revision']==1
        assert body['acknowledgement']=={'bookingId':identity,'requestId':key,'action':'accept',
                                         'eventAction':'accept','eventRevision':1}
        return True

    try:
        deadline = time.monotonic()+30
        while time.monotonic()<deadline:
            if process.poll() is not None:
                raise RuntimeError('TEST Gunicorn exited before accepting requests')
            try:
                status,health = request('/api/health')
                if status==200 and health['mode']=='test' and health['instanceId']==server.instance_id():
                    break
            except (ConnectionError,http.client.HTTPException):
                pass
            time.sleep(.1)
        else:
            raise RuntimeError('Could not identify the temporary TEST instance')

        barrier = threading.Barrier(len(jobs),timeout=45)
        def accept(job):
            barrier.wait()
            started = time.perf_counter()
            accepted = submit(job)
            return accepted,(time.perf_counter()-started)*1000

        with ThreadPoolExecutor(len(jobs)) as pool:
            outcomes = list(pool.map(accept,jobs))
        winners = [job for job,(won,_) in zip(jobs,outcomes) if won]
        assert len(winners)==len({sitter for sitter,_,_ in winners})==10
        for job in winners:
            if not submit(job):
                raise AssertionError('Accepted booking replay was rejected')
        return outcomes,winners
    finally:
        stop(process)


def run(directory, *, http=False):
    server,jobs,now = prepare_jobs(directory)
    outcomes,winners = race_http(server,jobs) if http else race_engine(server,jobs,now)
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
    report = dict(accounts=1000,concurrentAccepts=len(jobs),bookingStates=states,replayedAccepts=len(winners),
                commissionEntries=len(debits),acceptEvents=len(events),walletsReconciled=True,integrity='ok',
                foreignKeyErrors=0,
                sqlite=sqlite3.sqlite_version,journal=journal,platform=platform.system())

    report['httpLatency' if http else 'transactionLatency'] = timings([elapsed for _,elapsed in outcomes])
    if http:
        report.update(gunicornWorkers=2, threadsPerWorker=4, transport='loopback HTTP')
    return report


if __name__=='__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--http', action='store_true', help='Exercise the authenticated Gunicorn API on Linux')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='momiq-booking-contention-') as tmp:
        report=run(tmp,http=args.http)
    print(json.dumps(report,indent=2))
