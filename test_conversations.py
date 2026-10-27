import hashlib
import json
import secrets
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import server
import test_catalog
from test_media import fixture_image


class ConversationTests(unittest.TestCase):
    save = test_catalog.CatalogTests.save
    review = test_catalog.CatalogTests.review
    def setUp(self):
        test_catalog.CatalogTests.setUp(self)
        self.save(); self.review()
        self.tokens = {}
        with server.db() as con:
            for index, uid in enumerate(['customer', 'stranger', 'sitteronly']):
                account = server.default_account()
                account['profile'].update(first='Test', last=uid)
                con.execute('INSERT INTO users VALUES(?,?,?,0,?)', (uid, f'99890000000{index}', json.dumps(account), server.now()))
                con.execute('INSERT INTO user_roles VALUES(?,?)', (uid, 'sitter' if uid == 'sitteronly' else 'customer'))
            for uid in ['abc', 'customer', 'stranger', 'sitteronly']:
                token = secrets.token_hex(32); self.tokens[uid] = token
                con.execute('INSERT INTO sessions VALUES(?,?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), uid, 'client', time.time()+3600))
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_http)
        self.base = f'http://127.0.0.1:{self.http.server_port}'

    def stop_http(self):
        self.http.shutdown(); self.http.server_close(); self.thread.join()

    def req(self, path, method='GET', data=None, user='customer', status=200):
        headers = {'Authorization': 'Bearer '+self.tokens[user]}
        if data is not None: headers['Content-Type'] = 'application/json'
        request = Request(self.base + path, data=json.dumps(data).encode() if data is not None else None, method=method, headers=headers)
        try: response = urlopen(request)
        except HTTPError as error: response = error
        with response:
            self.assertEqual(response.status, status)
            return json.load(response)

    def create_chat(self, user='customer', status=200):
        return self.req('/api/conversations', 'POST', {'listingId': 'abc:boarding'}, user, status)

    def send_chat(self, identity, text='hello', user='customer', request=None, status=200, image=None):
        return self.req('/api/conversations/'+identity+'/messages', 'POST',
                        {'text':text,'requestId':request or secrets.token_hex(16),'image':image,'senderRole':'support'}, user, status)

    def test_participants_and_private_attachment(self):
        chat = self.create_chat(); identity = chat['id']
        self.assertEqual(self.create_chat()['id'], identity)
        image = fixture_image()
        sent = self.send_chat(identity, image=image)
        self.assertEqual(sent['senderRole'], 'customer')
        self.assertNotIn('image', sent)
        reply = self.send_chat(identity, 'sitter answer', 'abc')
        self.assertEqual(reply['senderRole'], 'sitter')
        self.assertTrue(reply['mine'])
        inbox = self.req('/api/conversations', user='abc')['items']
        self.assertEqual(inbox[0]['peerName'], 'Test c.')
        self.assertEqual(inbox[0]['unreadCount'], 1)
        self.assertEqual(self.req('/api/conversations', user='stranger')['items'], [])
        for suffix in ['', '/messages', '/messages/'+sent['id']+'/image']:
            self.req('/api/conversations/'+identity+suffix, user='stranger', status=404)
        self.send_chat(identity, user='stranger', status=404)
        self.req('/api/conversations/'+identity+'/read', 'POST', {'throughId':sent['id']}, user='stranger', status=404)
        self.assertEqual(self.req('/api/conversations/'+identity+'/messages/'+sent['id']+'/image', user='abc')['image'], image)

    def test_new_contact_gate_existing_conversation_survives_low_balance(self):
        self.create_chat('sitteronly', 403)
        self.create_chat('abc', 400)
        chat = self.create_chat()
        with server.db() as con: con.execute("UPDATE wallet_accounts SET balance_minor=0 WHERE user_id='abc'")
        self.assertEqual(self.create_chat()['id'], chat['id'])
        self.create_chat('stranger', 409)
        self.send_chat(chat['id'])
        self.send_chat(chat['id'], user='abc')
        with server.db() as con: con.execute("UPDATE users SET blocked=1 WHERE id='abc'")
        self.assertFalse(self.req('/api/conversations/'+chat['id'])['canSend'])
        self.send_chat(chat['id'], status=409)
        self.send_chat(chat['id'], user='abc', status=403)

    def test_parallel_retry_changed_content_and_cross_conversation_collision(self):
        identity = self.create_chat()['id']; request = secrets.token_hex(16)
        barrier = threading.Barrier(2)
        def post():
            barrier.wait()
            return self.send_chat(identity, request=request)['id']
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(lambda _: post(), range(2)))
        self.assertEqual(ids[0], ids[1])
        self.send_chat(identity, text='changed', request=request, status=409)
        self.send_chat(identity, image=fixture_image(), request=request, status=409)
        with server.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM conversation_messages').fetchone()[0], 1)
            self.assertEqual(con.execute("SELECT count FROM attempts WHERE key='conversation:send:customer'").fetchone()[0], 1)
        self.assertEqual(self.send_chat(identity, request=request)['id'], ids[0])
        other = secrets.token_hex(16)
        with server.db() as con:
            con.execute('INSERT INTO conversations(id,customer_id,sitter_id,service,customer_name,sitter_name,created) VALUES(?,?,?,?,?,?,?)',
                        (other, 'customer', 'abc', 'personal', 'Test c.', 'Test E.', server.now()))
        self.send_chat(other, request=request, status=409)

    def test_inbox_pages_and_invalid_cursors(self):
        self.create_chat()
        with server.db() as con:
            for i in range(31):
                uid = f'page{i}'
                con.execute('INSERT INTO users VALUES(?,?,?,0,?)', (uid, f'99891111{i:04d}', '{}', server.now()))
                con.execute('INSERT INTO conversations(id,customer_id,sitter_id,service,customer_name,sitter_name,created) VALUES(?,?,?,?,?,?,?)',
                            (secrets.token_hex(16), 'customer', uid, 'boarding', 'Test', 'Test', server.now()))
        first = self.req('/api/conversations')
        second = self.req('/api/conversations?before='+first['nextCursor'])
        self.assertEqual(len(first['items']), 30); self.assertEqual(len(second['items']), 2)
        self.assertIsNone(second['nextCursor'])
        self.assertFalse({x['id'] for x in first['items']} & {x['id'] for x in second['items']})
        for cursor in ['-1:1', '1', '0:0', 'nan:2']:
            self.req('/api/conversations?before='+cursor, status=400)

    def test_ordered_pagination_delta_and_monotonic_read_marker(self):
        identity = self.create_chat()['id']; base = '/api/conversations/'+identity
        sent = [self.send_chat(identity, text=str(i)) for i in range(34)]
        page = self.req(base+'/messages', user='abc')
        self.assertTrue(page['hasMore']); self.assertEqual(len(page['items']), 30)
        self.assertEqual(page['items'][0]['text'], '4')
        older = self.req(base+'/messages?before='+page['items'][0]['id'], user='abc')
        self.assertFalse(older['hasMore']); self.assertEqual([x['text'] for x in older['items']], ['0','1','2','3'])
        delta = self.req(base+'/messages?after='+sent[-2]['id'], user='abc')
        self.assertEqual([x['id'] for x in delta['items']], [sent[-1]['id']])
        self.req(base+'/messages?before=1&after=0', status=400)
        for uid in [sent[9]['id'], sent[4]['id']]:
            self.req(base+'/read', 'POST', {'throughId':uid}, user='abc')
        self.assertEqual(self.req(base, user='abc')['unreadCount'], 24)
        self.assertEqual(self.req(base)['peerReadThrough'], sent[9]['id'])
        new = self.send_chat(identity, 'arrived after view')
        self.req(base+'/read', 'POST', {'throughId':sent[-1]['id']}, user='abc')
        self.assertEqual(self.req(base, user='abc')['unreadCount'], 1)
        self.req(base+'/read', 'POST', {'throughId':str(int(new['id'])+1)}, user='abc', status=400)
        other = self.create_chat('stranger')['id']
        self.req('/api/conversations/'+other+'/read', 'POST', {'throughId':new['id']}, user='abc', status=400)

    def test_transactional_rate_limits_allow_known_retries(self):
        identity = self.create_chat()['id']; request = secrets.token_hex(16)
        first = self.send_chat(identity, request=request)
        with server.db() as con:
            con.execute("UPDATE attempts SET count=60 WHERE key='conversation:send:customer'")
        self.assertEqual(self.send_chat(identity, request=request)['id'], first['id'])
        self.send_chat(identity, status=429)
        with server.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM conversation_messages').fetchone()[0], 1)
