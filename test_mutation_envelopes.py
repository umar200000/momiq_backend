"""Unsupported authority/payload fields must fail before any mutation."""
import secrets
import unittest
from unittest.mock import patch

import catalog
import server
import wallet
import test_api
import test_conversations
import test_support_tickets
from test_media import fixture_image


def snapshot():
    with server.db() as con:
        return {name:[tuple(r) for r in con.execute('SELECT * FROM '+name)] for name in (
            'platform_settings','topup_requests','topup_history','topup_evidence_claims','wallet_accounts','wallet_entries',
            'notifications','audit','listing_moderation','listing_revisions','listings','conversation_messages','chat_reports','chat_report_history')}


class FinanceEnvelopeTests(unittest.TestCase):
    setUpClass=classmethod(test_api.ApiTests.setUpClass.__func__)
    tearDownClass=classmethod(test_api.ApiTests.tearDownClass.__func__)
    setUp=test_api.ApiTests.setUp
    req=test_api.ApiTests.req

    def test_settings_rejects_extra_fields_and_query_before_photo_or_write(self):
        config=self.req('/api/admin/platform-settings',admin=True)
        data={'version':config['version'],'commissionBps':1100,'reason':'TEST exact fields'}
        before=snapshot()
        for field in ('actor','balanceMinor','verified','unknown','termsVersion'):
            with patch.object(server,'photo',side_effect=AssertionError('Photo must not be decoded')):
                self.req('/api/admin/platform-settings','PUT',{**data,field:True},admin=True,expected=400)
            self.assertEqual(snapshot(),before)
        self.req('/api/admin/platform-settings?force=true','PUT',data,admin=True,expected=400)
        self.assertEqual(snapshot(),before)
        self.assertEqual(self.req('/api/admin/platform-settings','PUT',data,admin=True)['commissionBps'],1100)

    def test_topup_create_amend_and_review_reject_unsupported_authority_and_keep_valid_retry(self):
        owner=self.req('/api/auth/login','POST',{'phone':'998900012399','code':'111111','role':'sitter'})
        config=self.req('/api/admin/platform-settings',admin=True)
        config=self.req('/api/admin/platform-settings','PUT',{'version':config['version'],'qrImage':fixture_image('green'),
            'recipientName':'TEST recipient','qrActive':True,'testOnly':True,'reason':'TEST fixture'},admin=True)
        data={'amountMinor':10000,'receipt':fixture_image('orange'),'payerReference':'TEST envelope reference','paidAt':None,
              'requestId':'TEST create','qrVersion':config['version'],'termsVersion':wallet.TERMS_VERSION,'acceptNonRefundable':True}
        before=snapshot()
        for field in ('userId','status','reviewedBy','balanceMinor'):
            self.req('/api/wallet/topups','POST',{**data,field:'forged'},token=owner['token'],expected=400)
            self.assertEqual(snapshot(),before)
        self.req('/api/wallet/topups?approved=true','POST',data,token=owner['token'],expected=400)
        self.assertEqual(snapshot(),before)
        row=self.req('/api/wallet/topups','POST',data,token=owner['token'],expected=201)['topup']
        self.assertEqual(self.req('/api/wallet/topups','POST',data,token=owner['token'])['topup']['id'],row['id'])
        path='/api/admin/topups/'+row['id']+'/review'
        self.req(path,'POST',{'revision':0,'decision':'request_info','reason':'TEST clarify'},admin=True)
        amendment={**data,'revision':1,'requestId':'TEST amend'}
        amend='/api/wallet/topups/'+row['id']+'/amend';before=snapshot()
        self.req(amend,'POST',{**amendment,'status':'approved'},token=owner['token'],expected=400)
        self.req(amend+'?force=true','POST',amendment,token=owner['token'],expected=400)
        self.assertEqual(snapshot(),before)
        self.req(amend,'POST',amendment,token=owner['token'])
        decision={'revision':2,'decision':'approve','reason':'TEST incoming checked','fundsVerified':True,
                  'receivedAmountMinor':10000,'transferReference':'TEST-ENVELOPE-CREDIT'}
        before=snapshot()
        for field in ('userId','actor','amountMinor','commissionBps'):
            self.req(path,'POST',{**decision,field:'forged'},admin=True,expected=400)
            self.assertEqual(snapshot(),before)
        self.req(path+'?force=true','POST',decision,admin=True,expected=400)
        self.assertEqual(snapshot(),before)
        self.req(path,'POST',decision,admin=True)
        self.req(path,'POST',decision,admin=True)
        with server.db() as con:
            self.assertEqual(con.execute("SELECT count(*) FROM wallet_entries WHERE source_key=?",('topup:'+row['id'],)).fetchone()[0],1)
            self.assertEqual(wallet.balance(con,owner['userId']),10000)


class ModerationEnvelopeTests(unittest.TestCase):
    setUp=test_support_tickets.SupportTests.setUp
    save=test_support_tickets.SupportTests.save
    review=test_support_tickets.SupportTests.review
    stop_http=test_support_tickets.SupportTests.stop_http
    req=test_support_tickets.SupportTests.req
    admin=test_support_tickets.SupportTests.admin
    create_chat=test_conversations.ConversationTests.create_chat
    send_chat=test_conversations.ConversationTests.send_chat

    def test_listing_review_and_archive_reject_unknown_fields_without_advancing_revision(self):
        self.admin('/api/admin/me')
        with server.db() as con:revision=catalog.revision(con,'abc')
        data={'decision':'reject','reason':'TEST review','testOnly':True,'_revision':revision}
        path='/api/admin/listings/abc/boarding/review';before=snapshot()
        self.admin(path,{**data,'reviewedBy':'forged'},status=400)
        self.admin(path+'?force=true',data,status=400)
        archive='/api/me/listings/boarding/archive'
        self.req(archive,'POST',{'_revision':revision,'status':'approved'},user='abc',status=400)
        self.req(archive+'?force=true','POST',{'_revision':revision},user='abc',status=400)
        self.assertEqual(snapshot(),before)
        result=self.admin(path,data)
        result=self.req(archive,'POST',{'_revision':result['_revision']},user='abc')
        self.assertEqual(result['moderation']['boarding']['status'],'archived')

    def test_chat_review_rejects_forged_fields_and_query_without_redaction(self):
        self.admin('/api/admin/me')
        chat=self.create_chat()['id'];message=self.send_chat(chat,user='abc')
        report=self.req('/api/conversations/'+chat+'/reports','POST',{'messageId':message['id'],
            'reason':'TEST report','requestId':secrets.token_hex(16)})
        path='/api/admin/chat-reports/'+report['id']+'/review'
        data={'revision':0,'decision':'remove','reason':'TEST moderation'};before=snapshot()
        self.admin(path,{**data,'actor':'forged'},status=400)
        self.admin(path+'?force=true',data,status=400)
        self.assertEqual(snapshot(),before)
        self.assertEqual(self.admin(path,data)['status'],'removed')
