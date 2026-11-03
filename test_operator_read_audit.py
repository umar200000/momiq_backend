"""Private index/evidence reads must commit minimal audit before disclosure."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import admin_accounts
import admin_bookings
import booking_disputes
import chat_moderation
import server
import support_tickets
import wallet
import test_booking_disputes as fixtures


class OperatorReadAuditTests(unittest.TestCase):
    setUp=fixtures.DisputeTests.setUp
    save=fixtures.DisputeTests.save
    review=fixtures.DisputeTests.review
    quote=fixtures.DisputeTests.quote
    request=fixtures.DisputeTests.request
    act=fixtures.DisputeTests.act
    payload=fixtures.DisputeTests.payload
    report=fixtures.DisputeTests.report

    def check_read(self,module,method,path,action,metadata,invoke):
        replies=[]
        def reply(status,payload):
            # A second connection proves the event was committed before reply.
            with server.db() as other:
                row=other.execute('SELECT actor,target FROM audit WHERE action=? ORDER BY id DESC LIMIT 1',(action,)).fetchone()
                self.assertEqual(row['actor'],'TEST reader')
                self.assertEqual(json.loads(row['target']),metadata)
                self.assertNotIn('sensitive-search',row['target'])
                self.assertNotIn('TEST private evidence',row['target'])
            replies.append((status,payload))
        handler=SimpleNamespace(path=path,command='GET',reply=reply)
        with server.db() as con:invoke(handler,con,path.split('?')[0])
        self.assertEqual(replies[0][0],200)
        with server.db() as con:
            count=con.execute('SELECT count(*) FROM audit').fetchone()[0]
            before={name:[tuple(row) for row in con.execute('SELECT * FROM '+name)] for name in
                    ('bookings','wallet_entries','booking_disputes','dispute_events','booking_incidents','incident_events')}
        original=getattr(module,method)
        def fail(*args,**kwargs):
            original(*args,**kwargs)
            raise RuntimeError('TEST audit storage failure')
        replies.clear()
        with patch.object(module,method,side_effect=fail),self.assertRaises(RuntimeError):
            with server.db() as con:invoke(handler,con,path.split('?')[0])
        self.assertEqual(replies,[])
        with server.db() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM audit').fetchone()[0],count)
            for name,rows in before.items():self.assertEqual([tuple(row) for row in con.execute('SELECT * FROM '+name)],rows)

    def test_account_and_listing_indexes_audit_without_logging_search_text(self):
        for kind in ('users','listings'):
            self.check_read(admin_accounts,'audit_index','/api/admin/'+kind+'?q=sensitive-search','admin-'+kind+'-index',
                {'status':'all','role':'all','service':'all','searchPresent':True,'after':None},
                lambda h,c,p:admin_accounts.route(h,c,'TEST reader',p,server.account_snapshot,server.roles_for))

    def test_booking_index_audits_filters_without_search_terms(self):
        self.request()
        self.check_read(admin_bookings,'audit','/api/admin/bookings?q=sensitive-search&bucket=pending','admin-booking-index',
            {'before':None,'status':'all','bucket':'pending','searchPresent':True},
            lambda h,c,p:admin_bookings.route(h,c,'TEST reader',p))

    def test_chat_report_index_audit_is_atomic_and_query_is_strict(self):
        invoke=lambda h,c,p:chat_moderation.route(h,c,'TEST reader',p)
        self.check_read(chat_moderation,'audit','/api/admin/chat-reports?status=all&before=999','chat-report-list',
            {'status':'all','before':999},invoke)
        for query in ('status=','status=open&status=all','unknown=x','before=','before=1&before=2'):
            h=SimpleNamespace(path='/api/admin/chat-reports?'+query,command='GET',reply=lambda *args:self.fail('Invalid response'))
            with self.assertRaises(ValueError):
                with server.db() as con:invoke(h,con,'/api/admin/chat-reports')

    def test_dispute_list_detail_and_incident_history_audit_without_copying_evidence(self):
        booking=self.act(self.request());self.report(booking)
        with server.db() as con:
            booking_disputes.incident(con,booking['id'],'abc','late_cancellation',self.start,'TEST reader','TEST private evidence')
        invoke=lambda h,c,p:booking_disputes.route(h,c,'TEST reader',p,server.photo,'local')
        cases=[('/api/admin/disputes?status=open','dispute-list-view',{'bookingId':None,'before':None,'status':'open'}),
            ('/api/admin/disputes/'+booking['id']+'?before=999','dispute-detail-view',{'bookingId':booking['id'],'before':999,'status':None}),
            ('/api/admin/incidents','incident-list-view',{'bookingId':None,'userId':None,'before':None}),
            ('/api/admin/incidents/'+booking['id']+'/abc/history?before=999','incident-history-view',{'bookingId':booking['id'],'userId':'abc','before':999})]
        for path,action,metadata in cases:self.check_read(booking_disputes,'audit_view',path,action,metadata,invoke)

    def test_owner_dispute_read_does_not_create_operator_audit(self):
        booking=self.act(self.request());self.report(booking)
        replies=[];path='/api/bookings/'+booking['id']+'/dispute'
        h=SimpleNamespace(path=path,command='GET',reply=lambda *args:replies.append(args))
        with server.db() as con:count=con.execute('SELECT count(*) FROM audit').fetchone()[0]
        with server.db() as con:booking_disputes.route(h,con,'customer',path,server.photo,'local')
        self.assertEqual(replies[0][0],200)
        with server.db() as con:self.assertEqual(con.execute('SELECT count(*) FROM audit').fetchone()[0],count)

    def test_support_list_audits_subject_access_without_copying_subject(self):
        self.check_read(support_tickets,'audit_detail','/api/admin/support?status=open','support-list-view',
            {'ticketId':None,'before':None,'status':'open'},
            lambda h,c,p:support_tickets.route(h,c,'TEST reader',p,server.photo,'local'))

    def test_finance_indexes_settings_and_corrections_audit_before_reply(self):
        identity='a'*32
        with server.db() as con:
            con.execute("INSERT INTO topup_requests(id,user_id,amount_minor,receipt,receipt_hash,qr_version,terms_version,request_id,status,created,transfer_reference) VALUES(?,'abc',1000,'TEST synthetic','TEST hash',1,'v1','TEST fixture','approved','2026-10-29','TEST-XOLIS')",(identity,))
            version=wallet.settings(con)['version']
        invoke=lambda h,c,p:wallet.route(h,c,'TEST reader',p,server.photo,'local')
        cases=[('/api/admin/topups?status=approved','topup-list-view',{'status':'approved','cursor':None}),
               ('/api/admin/topups/'+identity+'/corrections','topup-corrections-view',{'topupId':identity,'before':None}),
               ('/api/admin/platform-settings','platform-settings-view',{'version':version}),
               ('/api/admin/platform-settings/history?before=999','platform-settings-history-view',{'before':999})]
        for path,action,metadata in cases:self.check_read(wallet,'audit_read',path,action,metadata,invoke)

    def test_finance_query_rejects_duplicate_unknown_and_empty_cursor(self):
        for path in ['/api/admin/topups?'+q for q in ('status=','status=all&status=pending','cursor=','cursor=invalid','unexpected=x')]+['/api/admin/platform-settings?unexpected=x']:
            h=SimpleNamespace(path=path,command='GET',reply=lambda *args:self.fail('Invalid response'))
            with self.assertRaises(ValueError):
                with server.db() as con:wallet.route(h,con,'TEST reader',path.split('?')[0],server.photo,'local')
