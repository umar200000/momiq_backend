"""Exercise HTTP retries after worker death during top-ups, booking debits and refunds in TEST."""
from contextlib import closing
import hashlib
import http.client
import json
import os
from pathlib import Path
import secrets
import signal
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

from tool.verify_proxy import port, stop


def crash_fixture(environ,start_response):
    import server
    import wsgi
    if server.ENVIRONMENT!='test':
        raise RuntimeError('TEST fixture required')
    arm=server.DATA/'worker-crash-test.json'
    if environ['REQUEST_METHOD']!='POST' or not arm.is_file():
        return wsgi.application(environ,start_response)
    spec=json.loads(arm.read_text())
    if environ['PATH_INFO']!=spec['path']:
        return wsgi.application(environ,start_response)
    commit=server.ClosingConnection.commit
    def stop_at_commit(con):
        if spec['phase']=='after':commit(con)
        arm.unlink()
        os.kill(os.getpid(),signal.SIGKILL)
    # Only the disposable, single-worker test WSGI entry point uses this hook.
    with patch.object(server.ClosingConnection,'commit',stop_at_commit):
        return wsgi.application(environ,start_response)


def verify_booking_recovery(data, db, request, interrupt):
    identity, sitter, snapshot = db.execute(
        "SELECT b.id,b.sitter_id,q.snapshot FROM bookings b JOIN booking_quotes q ON q.id=b.quote_id WHERE b.status='pending'"
    ).fetchone()
    commission = json.loads(snapshot)['price']['commission_minor']
    assert commission > 0
    token = secrets.token_urlsafe(40)
    with closing(sqlite3.connect(data / 'momiq.sqlite3')) as fixture:
        fixture.execute("INSERT INTO sessions VALUES(?,?,'client',?)",
                        (hashlib.sha256(token.encode()).hexdigest(), sitter, time.time()+600))
        fixture.commit()
    def balance():
        return db.execute('SELECT balance_minor FROM wallet_accounts WHERE user_id=?',(sitter,)).fetchone()[0]
    initial = balance()
    for revision, action, prior, final, source, change in (
            (0, 'accept', 'pending', 'accepted', 'commission', -commission),
            (1, 'cancel', 'accepted', 'cancelled', 'refund', commission)):
        path = f'/api/bookings/{identity}/{action}'
        payload = {'revision': revision, 'requestId': secrets.token_hex(16), 'reason': 'TEST worker recovery'}
        before = balance()
        def verify_state(committed):
            assert db.execute('SELECT status,revision FROM bookings WHERE id=?',(identity,)).fetchone() == (
                final if committed else prior, revision + committed)
            assert balance() == before + change * committed
            for sql, args, count in (
                ('SELECT COUNT(*) FROM wallet_entries WHERE source_key=?',(f'booking:{identity}:{source}',),1),
                ('SELECT COUNT(*) FROM booking_events WHERE booking_id=? AND action=?',(identity, action),1),
                ('SELECT COUNT(*) FROM booking_requests WHERE actor=? AND request_id=?',(sitter,payload['requestId']),1),
                ("SELECT COUNT(*) FROM audit WHERE action=? AND json_extract(target,'$.id')=?",('booking-'+action,identity),1),
                ('SELECT COUNT(*) FROM notifications WHERE source_key LIKE ?',(f'booking:{identity}:{revision+1}:%',),2)):
                assert db.execute(sql,args).fetchone()[0] == count * committed
        interrupt('before', path, payload, token=token)
        verify_state(False)
        interrupt('after', path, payload, token=token)
        verify_state(True)
        response,_ = request(path, payload, token=token)
        assert response['status'] == final and response['revision'] == revision + 1
        assert response['acknowledgement']['requestId'] == payload['requestId']
        verify_state(True)
    assert balance() == initial


def verify():
    with TemporaryDirectory(prefix='momiq-worker-drill-') as tmp:
        data=Path(tmp)/'fixture'
        password=secrets.token_urlsafe(24)
        env={**os.environ,'MOMIQ_ENV':'test','MOMIQ_ALLOW_TEST_LOGIN':'0',
             'MOMIQ_DATA_DIR':str(data),'MOMIQ_ADMIN_PASSWORD':password}
        for name in ('MOMIQ_AREA_FILE','MOMIQ_AREA_SHA256'):env.pop(name,None)
        root=Path(__file__).resolve().parents[1]
        subprocess.run([sys.executable,'seed_scenarios.py','--data-dir',str(data),'--payments'],
                       check=True,env=env,cwd=root,stdout=subprocess.DEVNULL)
        bind=port()
        process=subprocess.Popen([sys.executable,'-m','gunicorn','--workers','1','--bind',f'127.0.0.1:{bind}',
                                  'tool.verify_worker_recovery:crash_fixture'],env=env,cwd=root,
                                 stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        def request(path,body=None,cookie=None,*,token=None):
            conn=http.client.HTTPConnection('127.0.0.1',bind,timeout=10)
            try:
                headers={'Content-Type':'application/json'}
                if cookie:headers['Cookie']=cookie
                if token:headers['Authorization']='Bearer '+token
                conn.request('GET' if body is None else 'POST',path,
                             None if body is None else json.dumps(body).encode(),headers)
                res=conn.getresponse()
                if res.status!=200:raise RuntimeError(f'Test HTTP failure {res.status}')
                return json.load(res),res.getheader('Set-Cookie')
            finally:conn.close()
        def interrupt(phase,path,payload,**auth):
            marker=data/'worker-crash-test.json'
            marker.write_text(json.dumps({'path':path,'phase':phase}))
            try:request(path,payload,**auth)
            except (ConnectionResetError,http.client.RemoteDisconnected):pass
            else:raise AssertionError('Expected lost HTTP response')
            assert not marker.exists() and process.poll() is None
        try:
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                if process.poll() is not None:raise RuntimeError('Gunicorn master exited')
                try:
                    request('/api/ready')
                    break
                except (ConnectionError,http.client.HTTPException):time.sleep(.1)
            else:raise RuntimeError('Test instance did not become ready')
            _,header=request('/api/admin/login',{'username':'admin','password':password})
            cookie=header.split(';',1)[0]
            with closing(sqlite3.connect((data/'momiq.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
                pending=db.execute("SELECT id,revision,amount_minor,user_id FROM topup_requests WHERE status='pending' ORDER BY id").fetchall()
                assert len(pending)==2
                for phase,(identity,revision,amount,owner) in zip(('before','after'),pending):
                    path='/api/admin/topups/'+identity+'/review'
                    payload={'revision':revision,'decision':'approve','reason':'TEST crash recovery','fundsVerified':True,
                             'receivedAmountMinor':amount,'transferReference':'TEST-WORKER-'+phase.upper()}
                    def balance():
                        return db.execute('SELECT balance_minor FROM wallet_accounts WHERE user_id=?',(owner,)).fetchone()[0]
                    initial=balance()
                    interrupt(phase,path,payload,cookie=cookie)
                    assert balance()==initial+(amount if phase=='after' else 0)
                    result,_=request(path,payload,cookie)
                    assert result['topup']['status']=='approved' and result['topup']['revision']==revision+1
                    assert request(path,payload,cookie)[0]==result
                    assert balance()==initial+amount
                    for query,arg in [
                        ('SELECT COUNT(*) FROM wallet_entries WHERE source_key=?','topup:'+identity),
                        ("SELECT COUNT(*) FROM topup_history WHERE event='approve' AND topup_id=?",identity),
                        ("SELECT COUNT(*) FROM audit WHERE action='topup-approve' AND target=?",identity+': '+payload['reason']),
                        ('SELECT COUNT(*) FROM notifications WHERE source_key=?',f'topup-review:{identity}:{revision+1}')]:
                        assert db.execute(query,(arg,)).fetchone()[0]==1
                verify_booking_recovery(data, db, request, interrupt)
                assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok' and not db.execute('PRAGMA foreign_key_check').fetchone()
            print('Six Gunicorn worker deaths across top-ups, booking acceptance and cancellation; retries and ledger verified')
        finally:stop(process)


if __name__=='__main__':
    verify()
