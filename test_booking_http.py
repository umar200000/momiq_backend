from datetime import datetime, timedelta, timezone
import json
import secrets
from urllib.parse import urlencode
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

    def test_private_video_explanation_http_contract_and_retry(self):
        import booking_http, booking_videos
        start=datetime.fromisoformat(self.payload['startsAt']).replace(hour=12,minute=0,second=0,microsecond=0)
        self.payload.update(startsAt=start.isoformat(),endsAt=(start+timedelta(days=1)).isoformat())
        b=self.book();path='/api/bookings/'+b['id']
        self.req(path+'/accept','POST',{'revision':0,'requestId':secrets.token_hex(16)},user='abc')
        with patch.object(booking_http,'datetime') as clock:
            clock.now.return_value=start
            self.req(path+'/start','POST',{'revision':1,'requestId':secrets.token_hex(16)})
            self.req(path+'/start','POST',{'revision':2,'requestId':secrets.token_hex(16)},user='abc')
        data={'petId':'owned','day':start.date().isoformat(),'slot':'evening','reason':'TEST private reason','emergency':True,'requestId':secrets.token_hex(16)}
        with patch.object(booking_videos,'datetime') as clock:
            clock.now.return_value=start+timedelta(hours=5)
            endpoint=path+'/videos/explanations'
            self.req(endpoint,'POST',data,status=403)
            self.req(endpoint,'POST',data,user='stranger',status=404)
            self.req(endpoint,'POST',dict(data,slot=[]),user='abc',status=400)
            self.assertTrue(self.req(endpoint,'POST',data,user='abc')['ok'])
            self.assertTrue(self.req(endpoint,'POST',data,user='abc')['ok'])
            self.req(endpoint,'POST',dict(data,reason='changed'),user='abc',status=409)
            view=self.req(path+'/videos?day='+data['day'])
            self.assertEqual(view['followups'][0]['explanations'][0]['reason'],data['reason'])
            self.req(path+'/videos?day='+data['day'],user='stranger',status=404)

    def test_balance_gate_covers_stale_quotes_new_contacts_and_keeps_existing_care(self):
        import copy
        listing=copy.deepcopy(self.listing);listing['listings'][0]['price']=10000
        self.save(listing,2);self.review(3)
        def balance(value):
            with server.db() as con:con.execute("UPDATE wallet_accounts SET balance_minor=? WHERE user_id='abc'",(value*100,))
        for amount,visible in [(14999,False),(15000,True),(15001,True)]:
            balance(amount)
            ids=[s['id'] for s in self.req('/api/sitters')['sitters']]
            self.assertEqual('abc:boarding' in ids,visible)
        balance(15000)
        chat=self.req('/api/conversations','POST',{'listingId':'abc:boarding'})
        booking=self.book();path='/api/bookings/'+booking['id']
        stale=self.quote()
        accepted=self.req(path+'/accept','POST',{'revision':0,'requestId':secrets.token_hex(16)},user='abc')
        self.assertEqual(accepted['status'],'accepted')
        with server.db() as con:self.assertEqual(con.execute("SELECT balance_minor FROM wallet_accounts WHERE user_id='abc'").fetchone()[0],1400000)
        self.assertEqual(self.req('/api/sitters')['sitters'],[])
        self.req('/api/bookings/quotes','POST',self.payload,status=409)
        self.req('/api/bookings','POST',{'quoteId':stale['id'],'requestId':secrets.token_hex(16)},status=409)
        self.req('/api/conversations','POST',{'listingId':'abc:boarding'},user='stranger',status=409)
        self.assertEqual(self.req('/api/conversations','POST',{'listingId':'abc:boarding'})['id'],chat['id'])
        self.req('/api/conversations/'+chat['id']+'/messages','POST',{'text':'TEST existing obligation','requestId':secrets.token_hex(16)},user='abc')
        self.assertEqual(self.req(path,user='abc')['status'],'accepted')
        self.assertTrue(self.req(path+'/care')['canEditInstructions'])
        self.req(path+'/care',user='abc')
        balance(15000)
        self.assertEqual(self.req('/api/sitters')['sitters'][0]['id'],'abc:boarding')
        self.req('/api/conversations','POST',{'listingId':'abc:boarding'},user='stranger')
        self.quote()

    def test_listing_and_profile_edits_preserve_accepted_care_and_revisions(self):
        import copy, hashlib, time
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        booking=self.book();path='/api/bookings/'+booking['id']
        self.req(path+'/accept','POST',{'revision':0,'requestId':secrets.token_hex(16)},user='abc')
        listing=self.req('/api/me/listings',user='abc')
        changed=copy.deepcopy(listing);changed['listings'][0]['location']['address']='NEW TEST location'
        self.req('/api/me/listings','PUT',changed,user='abc',status=409)
        self.assertEqual(self.req('/api/me/listings',user='abc'),listing)
        account=self.req('/api/me',user='abc')['account']
        changed=copy.deepcopy(account);changed['sitterProfile']['housing']='apartment'
        self.req('/api/me','PUT',changed,user='abc',status=409)
        self.assertEqual(self.req('/api/me',user='abc')['account'],account)
        token=secrets.token_hex(32)
        with server.db() as con:
            con.execute("INSERT OR IGNORE INTO admins VALUES('test-admin','TEST salt','disabled')")
            con.execute("INSERT OR IGNORE INTO admin_permissions VALUES('test-admin','administrator',1)")
            con.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),'test-admin','admin',time.time()+3600))
        request=Request(self.base+'/api/admin/users/abc',method='PUT',
                        data=json.dumps({'account':changed,'_revision':account['_revision'],'reason':'TEST changed terms'}).encode(),
                        headers={'Cookie':'momiq_admin='+token,'Content-Type':'application/json'})
        with self.assertRaises(HTTPError) as caught:urlopen(request)
        self.assertEqual(caught.exception.code,409);caught.exception.close()
        self.assertEqual(self.req('/api/me',user='abc')['account'],account)

    def test_review_http_completed_ownership_public_projection_and_admin_gate(self):
        import booking_http, hashlib, time
        from urllib.request import Request, urlopen
        b=self.book();path='/api/bookings/'+b['id']
        review={'stars':4,'text':'TEST public review','revision':0,'action':'save','requestId':secrets.token_hex(16)}
        self.req(path+'/review','POST',review,status=409)
        self.assertFalse(self.req(path+'/review')['canCreate'])
        b=self.req(path+'/accept','POST',{'revision':0,'requestId':secrets.token_hex(16)},user='abc')
        start=datetime.fromisoformat(self.payload['startsAt'])
        with patch.object(booking_http,'datetime') as clock:
            clock.now.return_value=start
            for user in ['customer','abc']:
                b=self.req(path+'/start','POST',{'revision':b['revision'],'requestId':secrets.token_hex(16)},user=user)
            clock.now.return_value=start+timedelta(hours=1)
            for user in ['customer','abc']:
                b=self.req(path+'/complete','POST',{'revision':b['revision'],'requestId':secrets.token_hex(16)},user=user)
        saved=self.req(path+'/review','POST',review)['review'];rid=saved['id']
        self.req(path+'/review',user='stranger',status=404)
        self.req(path+'/review','POST',{**review,'revision':1,'requestId':secrets.token_hex(16),'text':'edited'},status=409)
        with urlopen(self.base+'/api/sitters/abc%3Aboarding/reviews') as response:
            page=json.load(response)
        self.assertEqual(page['items'][0]['text'],'TEST public review');self.assertEqual(page['count'],0)
        self.assertNotIn('bookingId',page['items'][0])
        self.req('/api/admin/reviews',status=401)
        self.req('/api/admin/reviews/'+rid+'/moderate','POST',{},status=401)
        token=secrets.token_hex(32)
        with server.db() as con:
            con.execute("INSERT OR IGNORE INTO admins VALUES('test-admin','TEST salt','disabled')")
            con.execute("INSERT OR IGNORE INTO admin_permissions VALUES('test-admin','administrator',1)")
            con.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),'test-admin','admin',time.time()+3600))
        def admin(target,body=None):
            req=Request(self.base+target,data=json.dumps(body).encode() if body else None,
                        headers={'Cookie':'momiq_admin='+token,'Content-Type':'application/json'})
            with urlopen(req) as response:return json.load(response)
        self.assertEqual(admin('/api/admin/reviews')['items'][0]['id'],rid)
        admin('/api/admin/reviews/'+rid+'/moderate',{'hidden':True,'revision':1,'reason':'TEST reason','requestId':secrets.token_hex(16)})
        self.assertEqual(self.req('/api/sitters/abc:boarding/reviews')['items'],[])
        self.assertEqual(len(admin('/api/admin/reviews/'+rid+'/history')['items']),2)
        self.req('/api/sitters/abc:boarding/reviews?before=0',status=400)
        self.req('/api/sitters/unknown:boarding/reviews',status=404)

    def test_care_http_is_participant_scoped_and_rejects_invalid_methods_and_queries(self):
        booking=self.book(); path='/api/bookings/'+booking['id']
        self.req(path+'/care',status=409)
        self.req(path+'/accept','POST',{'revision':0,'requestId':secrets.token_hex(16)},user='abc')
        payload={'petId':'owned','kind':'instructions','day':'','category':'','revision':0,
                 'requestId':secrets.token_hex(16),'payload':{'food':'TEST 08:00','water':'','walk':'','medicine':'','other':'','reason':'TEST new instructions'}}
        self.req(path+'/care','POST',payload,user='abc',status=403)
        self.req(path+'/care','POST',payload,user='stranger',status=404)
        saved=self.req(path+'/care','POST',payload)
        self.assertEqual(self.req(path+'/care','POST',payload),saved)
        current=self.req(path+'/care',user='abc')
        self.assertEqual(current['pets'][0]['instructions']['payload']['food'],'TEST 08:00')
        self.assertEqual(saved['bookingId'],booking['id'])
        self.assertEqual(saved['requestId'],payload['requestId'])
        self.assertEqual(self.req(path+'/care/history',user='abc')['items'][0],
                         {k:v for k,v in saved.items() if k not in ('bookingId','requestId')})
        self.req(path+'/care/history',user='stranger',status=404)
        for suffix in ['?day=bad','?day=2026-01-01&day=2026-01-02','?other=1','/history?before=0','/history?before=']:
            self.req(path+'/care'+suffix,status=400)
        self.req(path+'/care','DELETE',status=404)
        self.req(path+'/care/history','POST',{},status=404)
        self.req(path+'/care','POST',{**payload,'admin':True},status=400)

    def test_sitter_dashboard_scopes_counts_dates_and_private_metadata(self):
        self.req('/api/me/dashboard',status=403)
        self.req('/api/me/dashboard',user='stranger',status=403)
        empty=self.req('/api/me/dashboard',user='abc')
        self.assertEqual(empty['pendingCount'],0)
        self.assertEqual(empty['identityVerification'],'not_integrated')
        self.assertTrue(empty['profilePresent'])
        self.assertTrue(empty['listings'][0]['testOnly'])
        a=self.book()
        self.assertEqual(self.req('/api/me/dashboard',user='abc')['pendingCount'],1)
        self.req('/api/bookings/'+a['id']+'/accept','POST',{'revision':0,'requestId':secrets.token_hex(16)},user='abc')
        upcoming=self.req('/api/me/dashboard',user='abc')
        self.assertEqual(upcoming['pendingCount'],0)
        self.assertEqual(upcoming['upcoming']['items'][0]['id'],a['id'])
        self.assertEqual(upcoming['today']['items'],[])
        self.assertNotIn('PRIVATE',json.dumps(upcoming));self.assertNotIn('snapshot',upcoming['upcoming']['items'][0])
        # At the exact service start the booking moves from upcoming to today's list.
        start=datetime.fromisoformat(self.payload['startsAt'])
        with patch.object(server,'now',return_value=start.isoformat()):
            today=self.req('/api/me/dashboard',user='abc')
        self.assertEqual(today['upcoming']['items'],[])
        self.assertEqual(today['today']['items'][0]['id'],a['id'])
        self.assertEqual(today['activePetCount'],0)  # accepted is not claimed as actual care
        with server.db() as con: con.execute("UPDATE wallet_accounts SET balance_minor=1499999 WHERE user_id='abc'")
        low=self.req('/api/me/dashboard',user='abc')
        self.assertFalse(low['balanceEligible'])
        self.assertEqual(low['upcoming']['items'][0]['id'],a['id'])
        other=self.req('/api/me/dashboard',user='sitteronly')
        self.assertEqual(other['upcoming']['items'],[])

    def test_care_facts_are_immutable_and_emergency_contact_is_scoped(self):
        values={'vaccinations':'PRIVATE vaccine note', 'allergies':'PRIVATE allergy',
                'medications':'PRIVATE instruction', 'behavior':'PRIVATE behavior',
                'emergencyName':'PRIVATE emergency', 'emergencyPhone':'+998900000099'}
        with server.db() as con:
            account=json.loads(con.execute("SELECT account FROM users WHERE id='customer'").fetchone()[0])
            account['pets'][0].update(values)
            con.execute("UPDATE users SET account=? WHERE id='customer'",(json.dumps(account),))
        self.assertNotIn('PRIVATE',json.dumps(self.req('/api/sitters')))
        booking=self.book();path='/api/bookings/'+booking['id']
        sitter=self.req(path,user='abc')['snapshot']['pets'][0]
        self.assertEqual(sitter['allergies'],values['allergies'])
        self.assertNotIn('emergencyPhone',sitter);self.assertNotIn('emergencyName',sitter)
        self.assertEqual(booking['snapshot']['pets'][0]['emergencyPhone'],values['emergencyPhone'])
        self.req(path,user='stranger',status=404)
        for user in ['customer','abc','stranger']:
            self.assertNotIn('PRIVATE',json.dumps(self.req('/api/bookings',user=user)))
            self.assertEqual(self.req('/api/bookings?q=PRIVATE',user=user)['items'],[])
        with server.db() as con:
            account['pets'][0].update({k:'CHANGED' for k in values})
            con.execute("UPDATE users SET account=? WHERE id='customer'",(json.dumps(account),))
        accepted=self.req(path+'/accept','POST',{'revision':0,'requestId':secrets.token_hex(16)},user='abc')
        for field,value in values.items(): self.assertEqual(accepted['snapshot']['pets'][0][field],value)
        self.req(path+'/cancel','POST',{'revision':1,'requestId':secrets.token_hex(16),'reason':'TEST only'})
        sitter=self.req(path,user='abc')['snapshot']['pets'][0]
        self.assertNotIn('emergencyPhone',sitter)
        self.assertEqual(self.req(path)['snapshot']['pets'][0]['emergencyPhone'],values['emergencyPhone'])

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

    def test_booking_chat_is_shared_and_survives_low_balance(self):
        booking=self.book(); path='/api/bookings/'+booking['id']
        self.req(path+'/accept','POST',{'revision':0,'requestId':secrets.token_hex(16)},user='abc')
        with server.db() as con:
            con.execute("UPDATE wallet_accounts SET balance_minor=0 WHERE user_id='abc'")
        chat=self.req(path+'/conversation','POST',{},user='abc')
        self.assertEqual(chat['myRole'],'sitter')
        self.assertEqual(self.req(path+'/conversation','POST',{})['id'],chat['id'])
        index='/api/conversations/'+chat['id']+'/bookings'
        related=self.req(index)
        self.assertEqual([x['id'] for x in related['items']],[booking['id']])
        sitter_index=self.req(index,user='abc')
        self.assertEqual([x['id'] for x in sitter_index['items']],[booking['id']])
        self.assertEqual(sitter_index['items'][0]['myRole'],'sitter')
        self.assertNotIn('PRIVATE',json.dumps(related))
        self.assertNotIn('snapshot',json.dumps(related))
        self.req(index,user='stranger',status=404)
        self.req(path+'/conversation','POST',{},user='stranger',status=404)
        self.req(path+'/conversation','POST',{'customerId':'stranger'},status=400)
        self.req(index+'?before=-1',status=400)
        self.assertEqual(self.req(index+'?before=1')['items'],[])
        with server.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM conversations').fetchone()[0],1)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM wallet_entries WHERE kind='commission'").fetchone()[0],1)

    def test_booking_chat_respects_blocks_and_closed_unaccepted_requests(self):
        booking=self.book(); path='/api/bookings/'+booking['id']
        with server.db() as con:
            con.execute("INSERT INTO chat_blocks VALUES('customer','abc',1,1,?)",(server.now(),))
        self.req(path+'/conversation','POST',{},status=409)
        with server.db() as con:
            con.execute("UPDATE chat_blocks SET active=0 WHERE blocker_id='customer'")
        self.req(path+'/reject','POST',{'revision':0,'requestId':secrets.token_hex(16),'reason':'TEST decline'},user='abc')
        self.req(path+'/conversation','POST',{},status=409)
        with server.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM conversations').fetchone()[0],0)

    def test_search_is_unicode_literal_private_and_participant_scoped(self):
        with server.db() as con:
            account=json.loads(con.execute("SELECT account FROM users WHERE id='customer'").fetchone()[0])
            account['pets'][0].update(name='МомиҚ_%',notes='SECRET_CARE_SEARCH')
            con.execute("UPDATE users SET account=? WHERE id='customer'",(json.dumps(account),))
        booking=self.book(); identity=booking['id']
        path='/api/bookings?'+urlencode({'q':'мОмИқ_%'})
        found=self.req(path)['items']
        self.assertEqual([x['id'] for x in found],[identity])
        self.assertEqual(found[0]['service'],'boarding')
        self.assertEqual(found[0]['pets'],[{'name':'МомиҚ_%','type':'Mushuk'}])
        self.assertNotIn('PRIVATE',json.dumps(found))
        self.assertNotIn('SECRET_CARE_SEARCH',json.dumps(found))
        self.assertEqual(self.req(path,user='stranger')['items'],[])
        self.assertEqual(self.req('/api/bookings?'+urlencode({'q':'SECRET_CARE_SEARCH'}))['items'],[])
        self.assertEqual(self.req('/api/bookings?'+urlencode({'q':"%' OR 1=1 --"}))['items'],[])
        self.assertEqual(self.req('/api/bookings?q='+identity[:8])['items'][0]['id'],identity)
        self.assertEqual(self.req('/api/bookings?'+urlencode({'q':'Test c.'}),user='abc')['items'][0]['id'],identity)
        self.assertEqual(self.req('/api/bookings?'+urlencode({'q':'Test c.'}))['items'],[])
        chat=self.req('/api/bookings/'+identity+'/conversation','POST',{})
        self.assertEqual(self.req('/api/conversations/'+chat['id']+'/bookings?'+urlencode({'q':'момиҚ_%'}))['items'][0]['id'],identity)
        for query in ['bucket=invalid','status=pending&status=accepted','q='+('a'*81),'unknown=1','before=0']:
            self.req('/api/bookings?'+query,status=400)

    def test_status_buckets_search_and_pagination_compose(self):
        pending=self.book(); rejected=self.book(); accepted=self.book()
        self.req('/api/bookings/'+rejected['id']+'/reject','POST',{'revision':0,'requestId':secrets.token_hex(16),'reason':'TEST'},user='abc')
        self.req('/api/bookings/'+accepted['id']+'/accept','POST',{'revision':0,'requestId':secrets.token_hex(16)},user='abc')
        for bucket, identity in [('pending',pending['id']),('ongoing',accepted['id']),('history',rejected['id'])]:
            self.assertEqual([x['id'] for x in self.req('/api/bookings?bucket='+bucket+'&q=TEST')['items']],[identity])
        self.assertEqual(self.req('/api/bookings?bucket=history&status=accepted')['items'],[])
        self.assertEqual([x['id'] for x in self.req('/api/bookings?before=3')['items']],[rejected['id'],pending['id']])

    def test_agreement_changes_and_extensions_are_explicitly_refused(self):
        policy=self.req('/api/bookings/policy')
        self.assertFalse(policy['agreementEditable'])
        self.assertEqual(policy['amendmentMode'],'new_quote_and_request')
        self.assertFalse(policy['newRequestCancelsPrevious'])
        booking=self.book(); path='/api/bookings/'+booking['id']
        changes={'startsAt':'2030-01-01T00:00:00Z','petIds':['someone-else'], 'service':'personal', 'price':1}
        for method,suffix in [('PUT',''),('PATCH',''),('DELETE',''),('POST','/change'),('POST','/extend')]:
            for user in ['customer','abc']:
                response=self.req(path+suffix,method,changes,user=user,status=409)
                self.assertIn('Yangi so‘rov eskisini bekor qilmaydi',response['error'])
            self.req(path+suffix,method,changes,user='stranger',status=404)
        self.assertEqual(self.req(path),booking)
        following=self.book()
        self.assertNotEqual(following['id'],booking['id'])
        self.assertEqual(self.req(path),booking)
        with server.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM wallet_entries').fetchone()[0],0)

    def test_two_party_handover_and_completion_http(self):
        booking=self.book(); path='/api/bookings/'+booking['id']
        accepted=self.req(path+'/accept','POST',{'revision':0,'requestId':secrets.token_hex(16)},user='abc')
        def confirm(action, revision, user):
            return self.req(path+'/'+action,'POST',{'revision':revision,'requestId':secrets.token_hex(16)},user=user)
        with patch.object(server.booking_http,'datetime') as clock:
            clock.now.return_value=datetime.fromisoformat(self.payload['startsAt'])+timedelta(hours=1)
            first=confirm('start',accepted['revision'],'customer')
            self.assertEqual(first['status'],'accepted')
            active=confirm('start',first['revision'],'abc')
            self.assertEqual(active['status'],'active')
            first_done=confirm('complete',active['revision'],'customer')
            self.assertEqual(first_done['status'],'active')
            done=confirm('complete',first_done['revision'],'abc')
            self.assertEqual(done['status'],'completed')
            self.assertEqual(self.req(path)['confirmations']['complete'],{'mine':True,'peer':True})

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
