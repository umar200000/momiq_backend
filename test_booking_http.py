from datetime import datetime, timedelta, timezone
import json
import secrets
import unittest
from unittest.mock import patch

import server
import test_conversations
from test_media import fixture_image


class BookingHttpTests(unittest.TestCase):
    save = test_conversations.ConversationTests.save
    review = test_conversations.ConversationTests.review
    stop_http = test_conversations.ConversationTests.stop_http
    req = test_conversations.ConversationTests.req

    def setUp(self):
        test_conversations.ConversationTests.setUp(self)
        with server.db() as con:
            account=json.loads(con.execute("SELECT account FROM users WHERE id='customer'").fetchone()[0])
            account['pets']=[{'id':'owned','type':'Mushuk','name':'TEST'}]
            con.execute("UPDATE users SET account=? WHERE id='customer'",(json.dumps(account),))
            con.execute("UPDATE wallet_accounts SET balance_minor=100000000 WHERE user_id='abc'")
        start=datetime.now(timezone.utc)+timedelta(days=3)
        self.payload={'listingId':'abc:boarding','petIds':['owned'],
                      'startsAt':start.isoformat(),'endsAt':(start+timedelta(hours=24)).isoformat()}

    def quote(self, **overrides):
        return self.req('/api/bookings/quotes','POST',dict(self.payload,**overrides),status=201)

    def book(self):
        return self.req('/api/bookings','POST',{'quoteId':self.quote()['id'],'requestId':secrets.token_hex(16)})

    def test_full_request_accept_cancel_and_retry_http_flow(self):
        policy=self.req('/api/bookings/policy')
        self.assertEqual(policy['version'],'elapsed-24h-v1')
        self.assertEqual(policy['services'],['boarding','homeVisit','personal'])
        quote=self.quote()
        self.assertEqual(quote['snapshot']['price']['billable_days'],1)
        self.assertEqual(quote['snapshot']['price']['service_total_minor'],50000000)
        payload={'quoteId':quote['id'],'requestId':secrets.token_hex(16)}
        booking=self.req('/api/bookings','POST',payload)
        self.assertEqual(self.req('/api/bookings','POST',payload)['id'],booking['id'])
        identity=booking['id'];path='/api/bookings/'+identity
        self.assertNotIn('PRIVATE',json.dumps(booking))
        accepted=self.req(path+'/accept','POST',{'revision':0,'requestId':secrets.token_hex(16)},user='abc')
        self.assertEqual(accepted['status'],'accepted')
        self.assertIn('PRIVATE',json.dumps(self.req(path)))
        self.assertNotIn('PRIVATE',json.dumps(self.req('/api/bookings')))
        cancelled=self.req(path+'/cancel','POST',{'revision':1,'requestId':secrets.token_hex(16),'reason':'TEST cancellation'})
        self.assertEqual(cancelled['status'],'cancelled')
        self.assertEqual([v['action'] for v in cancelled['history']],['request','accept','cancel'])
        with server.db() as con:
            self.assertEqual(con.execute("SELECT balance_minor FROM wallet_accounts WHERE user_id='abc'").fetchone()[0],100000000)

    def test_unknown_fields_foreign_ids_roles_and_hosted_gate(self):
        self.req('/api/bookings/quotes','POST',dict(self.payload,total=1),status=400)
        self.req('/api/bookings/quotes','POST',dict(self.payload,billableDays=1),status=400)
        self.req('/api/bookings','POST',{'quoteId':{},'requestId':secrets.token_hex(16)},status=400)
        self.req('/api/bookings/quotes','POST',dict(self.payload,petIds=['foreign']),status=404)
        self.req('/api/bookings/quotes','POST',self.payload,user='sitteronly',status=403)
        booking=self.book(); path='/api/bookings/'+booking['id']
        self.req(path,user='stranger',status=404)
        self.req(path+'/accept','POST',{'revision':0,'requestId':secrets.token_hex(16)},status=403)
        self.req(path+'/cancel','POST',{'revision':0,'requestId':secrets.token_hex(16),'reason':'TEST'},user='stranger',status=404)
        self.req(path+'/accept','POST',{'requestId':secrets.token_hex(16)},user='abc',status=428)
        with patch.object(server,'ENVIRONMENT','production'):
            self.req('/api/bookings/policy',status=503)
            self.req('/api/bookings/quotes','POST',self.payload,status=503)
        with patch.object(server,'ENVIRONMENT','staging'):
            self.req(path,status=503)
        self.assertEqual(self.req('/api/bookings',user='stranger')['items'],[])
        self.req('/api/bookings?before=-1',status=400)
        self.req('/api/bookings?status=invalid',status=400)

    def test_paging_expiry_and_boundaries(self):
        for i in range(22):
            if i==20:
                with server.db() as con: con.execute("DELETE FROM attempts WHERE key LIKE 'conversation:booking_%'")
            self.book()
        first=self.req('/api/bookings')
        second=self.req('/api/bookings?before='+first['nextCursor'])
        self.assertEqual(len(first['items']),20);self.assertEqual(len(second['items']),2)
        self.assertIsNone(second['nextCursor'])
        self.assertFalse({x['id'] for x in first['items']} & {x['id'] for x in second['items']})
        self.assertEqual(self.req('/api/bookings?status=accepted')['items'],[])
        with server.db() as con:
            # Controlled clock advance, without rewriting immutable agreement.
            latest=con.execute('SELECT reply_deadline FROM bookings LIMIT 1').fetchone()[0]
        after=datetime.fromisoformat(latest)+timedelta(hours=1)
        with patch('booking_http.datetime') as clock:
            clock.now.return_value=after
            expired=self.req('/api/bookings?status=expired')
        self.assertEqual(len(expired['items']),20)
        self.assertTrue(all(item['status']=='expired' for item in expired['items']))

    def test_quote_rate_limit(self):
        for _ in range(30): self.quote()
        self.req('/api/bookings/quotes','POST',self.payload,status=429)
        with server.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM booking_quotes').fetchone()[0],30)

    def test_pet_evidence_is_private_lazy_immutable_and_deduplicated(self):
        photo=fixture_image()
        with server.db() as con:
            account=json.loads(con.execute("SELECT account FROM users WHERE id='customer'").fetchone()[0])
            account['pets'][0]['photo']=photo
            con.execute("UPDATE users SET account=? WHERE id='customer'",(json.dumps(account),))
        quote=self.quote(petPassports={'owned':photo})
        self.assertNotIn(photo,json.dumps(quote))
        self.assertTrue(quote['snapshot']['pets'][0]['hasPassport'])
        booking=self.req('/api/bookings','POST',{'quoteId':quote['id'],'requestId':secrets.token_hex(16)})
        path='/api/bookings/'+booking['id']+'/pets/owned/'
        for kind in ('photo','passport'):
            self.assertEqual(self.req(path+kind)['image'],photo)
            self.assertEqual(self.req(path+kind,user='abc')['image'],photo)
            self.req(path+kind,user='stranger',status=404)
        self.req('/api/bookings/'+booking['id']+'/pets/foreign/passport',status=404)
        with server.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM booking_media').fetchone()[0],1)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM booking_quote_media').fetchone()[0],2)
            account['pets'][0]['photo']=fixture_image('blue')
            con.execute("UPDATE users SET account=? WHERE id='customer'",(json.dumps(account),))
        self.assertEqual(self.req(path+'photo')['image'],photo)
        self.req('/api/bookings/quotes','POST',dict(self.payload,petPassports={'foreign':photo}),status=400)
        self.req('/api/bookings/quotes','POST',dict(self.payload,petPassports={'owned':'not-an-image'}),status=400)
        self.req('/api/bookings/quotes','POST',dict(self.payload,petPassports={'owned':None}),status=400)
