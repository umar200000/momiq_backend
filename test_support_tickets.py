import hashlib
import json
import secrets
import sqlite3
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from unittest.mock import patch

import server
import support_tickets as support
import notifications
import test_conversations
import test_booking_http
from test_media import fixture_image


class SupportTests(unittest.TestCase):
    setUp=test_booking_http.BookingHttpTests.setUp
    quote=test_booking_http.BookingHttpTests.quote
    book=test_booking_http.BookingHttpTests.book
    save=test_conversations.ConversationTests.save
    review=test_conversations.ConversationTests.review
    stop_http=test_conversations.ConversationTests.stop_http
    req=test_conversations.ConversationTests.req

    def data(self,**changes):
        return {'subject':'TEST help','topic':'general','bookingId':None,'text':'TEST message','image':None,
                'revision':0,'requestId':secrets.token_hex(16),'action':'reply',**changes}

    def reply(self,revision=1,**changes):
        return {'text':'TEST reply','image':None,'revision':revision,'requestId':secrets.token_hex(16),'action':'reply',**changes}

    def admin(self,path,body=None,status=200,binary=False):
        if not hasattr(self,'admin_token'):
            self.admin_token=secrets.token_hex(32)
            with server.db() as con:
                con.execute("INSERT OR IGNORE INTO admins VALUES('test-admin','TEST salt','disabled')")
                con.execute("INSERT OR IGNORE INTO admin_permissions VALUES('test-admin','administrator',1)")
                con.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(self.admin_token.encode()).hexdigest(),'test-admin','admin',time.time()+3600))
        req=Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Cookie':'momiq_admin='+self.admin_token,'Content-Type':'application/json'})
        try:response=urlopen(req)
        except HTTPError as e:response=e
        with response:
            self.assertEqual(response.status,status)
            return response.read() if binary else json.load(response)

    def test_owner_admin_boundaries_private_image_and_immutable_history(self):
        created=self.req('/api/support','POST',self.data(image=fixture_image()))
        identity=created['ticket']['id'];path='/api/support/'+identity
        self.req(path,user='stranger',status=404)
        self.req(path,'POST',self.reply(),user='stranger',status=404)
        self.req('/api/admin/support',status=401)
        self.assertTrue(created['items'][0]['hasImage']);self.assertNotIn('image',created['items'][0])
        image_path=path+'/messages/'+created['items'][0]['id']+'/image'
        self.req(image_path,user='stranger',status=404)
        self.assertEqual(self.admin(image_path.replace('/api/','/api/admin/'))['image'],fixture_image())
        self.assertEqual(self.req('/api/support',user='abc')['items'],[])
        self.req(path,'POST',self.reply(action='resolve'),status=400)
        with server.db() as con:
            with self.assertRaises(sqlite3.IntegrityError):con.execute("UPDATE support_messages SET text='changed'")

    def test_legacy_support_author_is_server_owned_and_read_reply_delete_audit_names_operator(self):
        with server.db() as con:con.execute('INSERT INTO sitters(id,profile) VALUES(?,?)',('test-legacy',json.dumps({'name':'TEST legacy sitter'})))
        path='/api/admin/users/abc/messages'
        self.req(path,user='abc',status=401)
        self.admin('/api/conversations/'+'a'*32+'/messages',status=401)
        self.admin(path)
        result=self.admin(path,{'sitter':'test-legacy','text':'TEST support','requestId':'test-operator-reply','senderRole':'sitter','mine':True})
        message=result['messages'][-1]
        self.assertEqual(message['senderRole'],'support');self.assertFalse(message['mine'])
        # Cookie-only administrator credentials never become client authority.
        req=Request(self.base+'/api/admin/messages/'+message['id'],method='DELETE',data=json.dumps({'reason':'TEST legacy cleanup'}).encode(),headers={'Cookie':'momiq_admin='+self.admin_token,'Content-Type':'application/json'})
        with urlopen(req) as response:self.assertEqual(response.status,200)
        with server.db() as con:
            rows=con.execute("SELECT actor,action FROM audit WHERE action IN ('legacy-chat-view','reply','delete-message') ORDER BY id").fetchall()
            self.assertEqual([(r['actor'],r['action']) for r in rows],[('test-admin','legacy-chat-view'),('test-admin','reply'),('test-admin','delete-message')])

    def test_parallel_exact_retry_one_ticket_changed_retry_conflicts(self):
        data=self.data();gate=threading.Barrier(2)
        def create(_):
            gate.wait()
            with server.db() as con:return support.write(con,'customer',None,data,server.photo)['ticket']['id']
        with ThreadPoolExecutor(max_workers=2) as pool:ids=list(pool.map(create,range(2)))
        self.assertEqual(ids[0],ids[1])
        self.req('/api/support','POST',{**data,'text':'Changed'},status=409)
        with server.db() as con:self.assertEqual(con.execute('SELECT COUNT(*) FROM support_messages').fetchone()[0],1)

    def test_both_booking_parties_create_private_tickets_without_financial_side_effects(self):
        # All fixtures are in the isolated temporary HTTP-test database.
        booking=self.book()
        with server.db() as con:balances=[tuple(r) for r in con.execute('SELECT * FROM wallet_accounts ORDER BY user_id')]
        customer=self.req('/api/support','POST',self.data(topic='booking',bookingId=booking['id']))
        sitter=self.req('/api/support','POST',self.data(topic='booking',bookingId=booking['id']),user='abc')
        self.assertNotEqual(customer['ticket']['id'],sitter['ticket']['id'])
        self.req('/api/support/'+customer['ticket']['id'],user='abc',status=404)
        self.req('/api/support','POST',self.data(topic='booking',bookingId=booking['id']),user='stranger',status=404)
        self.admin('/api/admin/support/'+customer['ticket']['id'],self.reply(action='resolve',text='TEST resolved'))
        self.assertEqual(self.req('/api/bookings/'+booking['id'])['status'],booking['status'])
        with server.db() as con:
            self.assertEqual([tuple(r) for r in con.execute('SELECT * FROM wallet_accounts ORDER BY user_id')],balances)
            account=json.loads(con.execute("SELECT account FROM users WHERE id='customer'").fetchone()[0])
            account['support']=[{'id':'old','text':'TEST historical message'}]
            con.execute("UPDATE users SET account=? WHERE id='customer'",(json.dumps(account),))
        self.assertEqual(self.req('/api/support')['legacyItems'],account['support'])
        self.assertEqual(self.req('/api/support',user='abc')['legacyItems'],[])

    def test_support_label_resolution_reopen_revision_and_atomic_notification(self):
        created=self.req('/api/support','POST',self.data());identity=created['ticket']['id'];path='/api/admin/support/'+identity
        reply=self.reply()
        original=notifications.publish
        def fail(*args):original(*args);raise RuntimeError('TEST rollback')
        with patch.object(notifications,'publish',side_effect=fail):
            with self.assertRaises(RuntimeError):
                with server.db() as con:support.write(con,'operator',identity,reply,server.photo,True)
        self.assertEqual(self.req('/api/support/'+identity)['ticket']['revision'],1)
        result=self.admin(path,reply)
        self.assertEqual(result['ticket']['status'],'waiting_user');self.assertEqual(result['items'][-1]['authorRole'],'support')
        self.admin(path,reply)
        self.admin(path,self.reply(text='Stale'),status=409)
        self.admin(path,self.reply(2,action='resolve',text='TEST solved'))
        result=self.req('/api/support/'+identity,'POST',self.reply(3,text='TEST still need help'))
        self.assertEqual(result['ticket']['status'],'open')
        with server.db() as con:self.assertEqual(con.execute("SELECT COUNT(*) FROM notifications WHERE source_key LIKE 'support:%'").fetchone()[0],2)

    def test_filters_paging_invalid_shape_booking_ownership_and_block(self):
        for data in [self.data(stars=5),self.data(subject=''),self.data(topic='wrong'),self.data(bookingId='a'*32),self.data(revision=True)]:
            self.req('/api/support','POST',data,status=404 if data.get('bookingId') else 400)
        created=self.req('/api/support','POST',self.data());identity=created['ticket']['id']
        for revision in range(1,24):
            self.admin('/api/admin/support/'+identity,self.reply(revision,text='TEST '+str(revision)))
        page=self.req('/api/support/'+identity)
        self.assertEqual(len(page['items']),20)
        old=self.req('/api/support/'+identity+'?before='+page['nextCursor'])
        self.assertEqual(len(old['items']),4)
        self.assertFalse(set(m['id'] for m in old['items']) & set(m['id'] for m in page['items']))
        self.assertEqual(self.req('/api/support?status=resolved')['items'],[])
        for suffix in ['?before=0','?unknown=1','?before=2&before=3']:
            self.req('/api/support'+suffix,status=400)
        with server.db() as con:con.execute("UPDATE users SET blocked=1 WHERE id='customer'")
        self.req('/api/support/'+identity,status=403)


if __name__=='__main__':unittest.main()
