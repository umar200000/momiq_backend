import hashlib
import json
import secrets
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import server
import test_conversations
from test_media import fixture_image


class ChatModerationTests(unittest.TestCase):
    setUp = test_conversations.ConversationTests.setUp
    stop_http = test_conversations.ConversationTests.stop_http
    req = test_conversations.ConversationTests.req
    create_chat = test_conversations.ConversationTests.create_chat
    send_chat = test_conversations.ConversationTests.send_chat
    save = test_conversations.ConversationTests.save
    review = test_conversations.ConversationTests.review

    def admin_req(self, path, data=None, actor='operator-one', status=200):
        token = hashlib.sha256(actor.encode()).hexdigest()
        with server.db() as con:
            con.execute('INSERT OR IGNORE INTO sessions VALUES(?,?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), actor, 'admin', time.time()+3600))
        request = Request(self.base+'/api/admin'+path, data=json.dumps(data).encode() if data is not None else None,
                          headers={'Content-Type':'application/json', 'Cookie':'momiq_admin='+token})
        try: response = urlopen(request)
        except HTTPError as error: response = error
        with response:
            self.assertEqual(response.status, status)
            return json.load(response)

    def report(self, identity, message, reason='TEST abusive message', request=None, status=200, user='customer'):
        return self.req('/api/conversations/'+identity+'/reports', 'POST', {'messageId':message, 'reason':reason, 'requestId':request or secrets.token_hex(16)}, user, status)

    def test_block_is_account_pair_scoped_revisioned_and_does_not_erase_history(self):
        identity = self.create_chat()['id']; path = '/api/conversations/'+identity
        first = self.send_chat(identity, user='abc')
        self.req(path+'/block', 'POST', {'blocked':True,'revision':0}, user='stranger', status=404)
        blocked = self.req(path+'/block', 'POST', {'blocked':True,'revision':0})
        self.assertTrue(blocked['blockedByMe']); self.assertFalse(blocked['canSend'])
        self.assertEqual(self.req(path+'/block', 'POST', {'blocked':True,'revision':0})['blockRevision'], 1)
        self.send_chat(identity, user='abc', status=409); self.send_chat(identity, status=409)
        # Cannot evade with a different service, even if it were discoverable.
        self.req('/api/conversations', 'POST', {'listingId':'abc:personal'}, status=409)
        self.assertEqual(self.req(path+'/messages')['items'][0]['id'], first['id'])
        self.req(path+'/block','POST',{'blocked':True,'revision':0},user='abc')
        self.req(path+'/block','POST',{'blocked':False,'revision':1})
        self.assertFalse(self.req(path)['canSend'])  # peer's independent block remains
        self.req(path+'/block','POST',{'blocked':True,'revision':0},status=409)
        self.req(path+'/block','POST',{'blocked':False,'revision':1},user='abc')
        self.assertTrue(self.req(path)['canSend'])
        self.send_chat(identity)

    def test_report_scope_retry_and_audited_private_evidence(self):
        identity = self.create_chat()['id']; message = self.send_chat(identity, user='abc', image=fixture_image())
        self.report(identity, message['id'], user='stranger', status=404)
        self.report(identity, message['id'], user='abc', status=404)
        request = secrets.token_hex(16)
        report = self.report(identity, message['id'], request=request)
        self.assertEqual(self.report(identity, message['id'], request=request)['id'], report['id'])
        self.report(identity, message['id'], reason='changed', request=request, status=409)
        self.assertEqual(len(self.req('/api/conversations/'+identity+'/reports')['items']), 1)
        self.assertEqual(self.req('/api/conversations/'+identity+'/reports', user='abc')['items'], [])
        path = '/chat-reports/'+report['id']
        self.req('/api/admin'+path+'/evidence',status=401)
        evidence = self.admin_req(path+'/evidence')
        self.assertEqual(evidence['message']['text'], 'hello')
        self.assertNotIn('image', evidence['message'])
        self.assertEqual(self.admin_req(path+'/image')['image'], fixture_image())
        with server.db() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM audit WHERE actor='operator-one' AND action LIKE 'chat-report-%'").fetchone()[0], 2)

    def test_parallel_moderation_redacts_old_pages_without_destroying_evidence(self):
        identity = self.create_chat()['id']; path = '/api/conversations/'+identity
        image = fixture_image(); message = self.send_chat(identity, user='abc', image=image)
        initial = self.req(path+'/messages')
        report = self.report(identity, message['id']); review = '/chat-reports/'+report['id']+'/review'
        data = {'revision':0,'decision':'remove','reason':'TEST confirmed violation'}
        # Run independent moderator sessions against one report revision.
        barrier = threading.Barrier(2)
        def post(actor):
            token = hashlib.sha256(actor.encode()).hexdigest()
            with server.db() as con:
                con.execute('INSERT OR IGNORE INTO sessions VALUES(?,?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), actor, 'admin', time.time()+3600))
            barrier.wait()
            request = Request(self.base+'/api/admin'+review, data=json.dumps(data).encode(), headers={'Content-Type':'application/json','Cookie':'momiq_admin='+token})
            try: response = urlopen(request)
            except HTTPError as error: response = error
            with response: return actor, response.status
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(post, ['operator-one','operator-two']))
        self.assertEqual(sorted(x[1] for x in results), [200,409])
        winner = next(x[0] for x in results if x[1] == 200)
        self.admin_req(review, data, actor=winner)
        self.admin_req(review, dict(data, decision='dismiss'), actor=winner, status=409)
        delta = self.req(path+'/messages?after='+message['id']+'&changesAfter='+initial['changeCursor'])
        self.assertEqual(delta['items'], []); self.assertEqual(delta['redactedIds'], [message['id']])
        redacted = self.req(path+'/messages')['items'][0]
        self.assertTrue(redacted['hidden']); self.assertEqual(redacted['text'], ''); self.assertFalse(redacted['hasImage'])
        self.req(path+'/messages/'+message['id']+'/image',status=404)
        evidence = self.admin_req('/chat-reports/'+report['id']+'/evidence')
        self.assertEqual(evidence['message']['text'], 'hello')
        self.assertEqual(len(evidence['history']), 2)
        self.assertEqual(self.admin_req('/chat-reports/'+report['id']+'/image')['image'], image)
        self.assertEqual(self.req(path+'/reports')['items'][0]['status'], 'removed')
        with server.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM chat_changes').fetchone()[0], 1)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM audit WHERE action='chat-report-remove'").fetchone()[0], 1)

    def test_dismiss_does_not_hide_message_and_review_requires_revision_reason(self):
        identity = self.create_chat()['id']; message = self.send_chat(identity,user='abc')
        report = self.report(identity,message['id']); path='/chat-reports/'+report['id']+'/review'
        self.admin_req(path, {'decision':'dismiss','reason':'TEST'},status=428)
        self.admin_req(path, {'revision':0,'decision':'dismiss','reason':''},status=400)
        self.admin_req(path, {'revision':0,'decision':'dismiss','reason':'TEST no violation'})
        self.assertFalse(self.req('/api/conversations/'+identity+'/messages')['items'][0]['hidden'])
        self.assertEqual(self.admin_req('/chat-reports')['items'], [])
        self.assertEqual(self.admin_req('/chat-reports?status=dismissed')['items'][0]['id'], report['id'])
