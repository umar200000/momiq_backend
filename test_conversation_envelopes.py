"""Rejected client envelopes must not advance chat, evidence, quotas or notices."""
import secrets
import unittest
import server
import test_conversations
import test_support_tickets


class ConversationEnvelopeTests(unittest.TestCase):
    setUp=test_conversations.ConversationTests.setUp
    stop_http=test_conversations.ConversationTests.stop_http
    req=test_conversations.ConversationTests.req
    create_chat=test_conversations.ConversationTests.create_chat
    send_chat=test_conversations.ConversationTests.send_chat
    save=test_conversations.ConversationTests.save
    review=test_conversations.ConversationTests.review
    admin=test_support_tickets.SupportTests.admin
    support_data=test_support_tickets.SupportTests.data

    def snapshot(self):
        with server.db() as con:
            names=[r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            return {name:sorted([tuple(r) for r in con.execute('SELECT * FROM "'+name.replace('"','""')+'"')],key=repr) for name in names}

    def test_unknown_write_fields_and_query_overrides_leave_all_tables_unchanged(self):
        chat=self.create_chat()['id'];message=self.send_chat(chat,user='abc');base='/api/conversations/'+chat
        writes=[('/api/conversations',{'listingId':'abc:boarding'}),
                (base+'/messages',{'text':'TEST message','requestId':secrets.token_hex(16),'image':None}),
                (base+'/read',{'throughId':message['id']}),
                (base+'/received',{'throughId':message['id']}),
                (base+'/block',{'blocked':True,'revision':0}),
                (base+'/reports',{'messageId':message['id'],'reason':'TEST report','requestId':secrets.token_hex(16)})]
        before=self.snapshot()
        for path,data in writes:
            for field,value in [('senderRole','support'),('userId','abc'),('status','approved')]:
                self.req(path,'POST',{**data,field:value},status=400)
            self.req(path+'?force=true','POST',data,status=400)
        self.assertEqual(self.snapshot(),before)
        result=self.req(base+'/messages','POST',writes[1][1]);retry=self.req(base+'/messages','POST',writes[1][1])
        self.assertEqual(result,retry);self.assertEqual(result['senderRole'],'customer')

    def test_ambiguous_read_queries_do_not_advance_receipts_or_hide_data(self):
        chat=self.create_chat()['id'];message=self.send_chat(chat,user='abc');base='/api/conversations/'+chat
        before=self.snapshot()
        for path in ('/api/conversations?before=0:1&before=0:2','/api/conversations?before=',
                     '/api/conversations?userId=abc',base+'?before=1',base+'/messages?before=',
                     base+'/messages?after=0&after=1',base+'/messages?changesAfter=',
                     base+'/messages?ownerId=abc',base+'/reports?before=1&before=2',
                     base+'/reports?before=',base+'/reports?status=open',
                     base+'/messages/'+message['id']+'/image?before=1'):
            self.req(path,status=400)
        self.assertEqual(self.snapshot(),before)
        page=self.req(base+'/messages?after=0&changesAfter=0')
        self.assertEqual(page['items'][0]['id'],message['id'])
        self.assertEqual(self.snapshot(),before)

    def test_support_review_and_json_booking_query_overrides_are_rejected_before_writes(self):
        created=self.req('/api/support','POST',self.support_data())
        path='/api/support/'+created['ticket']['id']
        self.admin('/api/admin/support/'+created['ticket']['id'])
        before=self.snapshot()
        self.req('/api/support?owner=abc','POST',self.support_data(),status=400)
        reply={'text':'TEST reply','image':None,'revision':1,'requestId':secrets.token_hex(16),'action':'reply'}
        self.req(path+'?force=true','POST',reply,status=400)
        self.admin(path.replace('/api/','/api/admin/')+'?force=true',reply,status=400)
        self.admin('/api/admin/reviews/1/moderate?force=true',{},status=400)
        for route in ('/api/bookings','/api/bookings/quotes','/api/bookings/'+'a'*32+'/review',
                      '/api/bookings/'+'a'*32+'/accept'):
            self.req(route+'?force=true','POST',{},status=400)
        self.assertEqual(self.snapshot(),before)
