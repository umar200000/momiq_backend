"""Real HTTP retry after an isolated test service exits before or after COMMIT."""
from contextlib import contextmanager
import hashlib
import http.client
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import server


def run_fixture(directory, channel, phase):
    server.DATA = Path(directory)
    commit = server.ClosingConnection.commit

    def crash(connection):
        if phase == 'after':
            commit(connection)
        os._exit(71)

    if phase:
        server.ClosingConnection.commit = crash
    with server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler) as http:
        channel.send(http.server_port)
        channel.close()
        http.serve_forever()


@contextmanager
def service(directory, phase=None):
    ctx = multiprocessing.get_context('spawn')
    receive, send = ctx.Pipe(duplex=False)
    process = ctx.Process(target=run_fixture, args=(directory, send, phase))
    process.start()
    send.close()
    try:
        if not receive.poll(15):
            raise RuntimeError('TEST service startup timed out')
        yield process, receive.recv()
    finally:
        receive.close()
        if process.is_alive():
            process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
        process.close()


def request(port, method, path, body):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    try:
        conn.request(method, path, json.dumps(body), {'Content-Type':'application/json','Cookie':'momiq_admin=test-recovery'})
        response = conn.getresponse()
        return response.status, json.load(response)
    finally:
        conn.close()


class RestartTests(unittest.TestCase):
    def test_operator_reply_and_redaction_after_lost_response(self):
        for phase in ('before','after'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp, patch.object(server,'DATA',Path(tmp)):
                server.setup()
                with server.db() as con:
                    con.execute("INSERT INTO users VALUES('ab','998000000000','{}',0,'TEST')")
                    con.execute("INSERT INTO sitters VALUES('test','{}',1)")
                    con.execute("INSERT INTO sessions VALUES(?,'admin','admin',?)",
                                (hashlib.sha256(b'test-recovery').hexdigest(),time.time()+600))
                path='/api/admin/users/ab/messages'
                payload={'sitter':'test','text':'TEST reply','requestId':'retry-on-restart'}
                for method, action in [('POST','reply'),('DELETE','delete-message')]:
                    with service(tmp,phase) as (process,port):
                        with self.assertRaises((http.client.RemoteDisconnected,ConnectionResetError)):
                            request(port,method,path,payload)
                        process.join(timeout=5)
                        self.assertEqual(process.exitcode,71)
                    with server.db() as con:
                        count=con.execute('SELECT COUNT(*) FROM audit WHERE action=?',(action,)).fetchone()[0]
                        self.assertEqual(count,int(phase=='after'))
                    with service(tmp) as (_,port):
                        status,result=request(port,method,path,payload)
                        self.assertEqual(status,200)
                        self.assertEqual(request(port,method,path,payload),(status,result))
                        if method=='POST':
                            self.assertEqual(len(result['messages']),1)
                            self.assertEqual(request(port,method,path,{**payload,'text':'changed'})[0],409)
                            path='/api/admin/messages/'+result['messages'][0]['id']
                            payload={}
                    with server.db() as con:
                        self.assertEqual(con.execute('SELECT COUNT(*) FROM audit WHERE action=?',(action,)).fetchone()[0],1)
                        self.assertEqual(con.execute('SELECT COUNT(*) FROM messages').fetchone()[0],1)
                        self.assertEqual(con.execute('SELECT deleted FROM messages').fetchone()[0],int(method=='DELETE'))
                        self.assertEqual(con.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                        self.assertFalse(con.execute('PRAGMA foreign_key_check').fetchone())
