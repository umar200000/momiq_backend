"""Private finance evidence reads, using only the temporary HTTP-test database."""
import json
import unittest
from unittest.mock import patch

import server
import wallet
import test_api
from test_media import fixture_image


class WalletReadAuditTests(unittest.TestCase):
    setUpClass=classmethod(test_api.ApiTests.setUpClass.__func__)
    tearDownClass=classmethod(test_api.ApiTests.tearDownClass.__func__)
    setUp=test_api.ApiTests.setUp
    req=test_api.ApiTests.req

    def test_receipt_and_history_reads_are_audited_without_money_or_private_content(self):
        owner=self.req('/api/auth/login','POST',{'phone':'998900012345','code':'111111','role':'sitter'})
        settings=self.req('/api/admin/platform-settings',admin=True)
        settings=self.req('/api/admin/platform-settings','PUT',{
            'version':settings['version'],'qrImage':fixture_image('purple'),'testOnly':True,
            'reason':'TEST read audit fixture','recipientName':'TEST recipient','qrActive':True,
        },admin=True)
        receipt=fixture_image('yellow')
        topup=self.req('/api/wallet/topups','POST',{
            'payerReference':'TEST private incoming reference','paidAt':'2026-10-26T10:00:00+05:00',
            'requestId':'TEST-private-read','amountMinor':10000,'receipt':receipt,
            'qrVersion':settings['version'],'termsVersion':wallet.TERMS_VERSION,'acceptNonRefundable':True,
        },token=owner['token'],expected=201)['topup']
        identity=topup['id']
        routes=['/receipt','/history','/history/0/receipt']
        prefix='/api/admin/topups/'+identity

        def records():
            with server.db() as con:
                return [dict(r) for r in con.execute("SELECT actor,action,target FROM audit WHERE action IN ('topup-receipt-view','topup-history-view','topup-history-receipt-view') ORDER BY id")]

        def financial_snapshot():
            with server.db() as con:
                return {name:[tuple(r) for r in con.execute('SELECT * FROM '+name)] for name in (
                    'topup_requests','topup_history','topup_evidence_claims','wallet_accounts','wallet_entries','notifications')}

        before=financial_snapshot()
        for suffix in routes:
            self.req('/api/wallet/topups/'+identity+suffix,token=owner['token'])
            self.req(prefix+suffix,token=owner['token'],expected=401)
        self.assertEqual(records(),[])
        self.assertEqual(self.req(prefix+'/receipt',admin=True)['receipt'],receipt)
        self.req(prefix+'/history',admin=True)
        self.assertEqual(self.req(prefix+'/history/0/receipt',admin=True)['receipt'],receipt)
        audit=records()
        self.assertEqual([r['actor'] for r in audit],['admin']*3)
        self.assertEqual([r['action'] for r in audit],['topup-receipt-view','topup-history-view','topup-history-receipt-view'])
        self.assertEqual([json.loads(r['target']) for r in audit],[
            {'topupId':identity,'revision':0},{'topupId':identity,'before':None},{'topupId':identity,'revision':0}])
        serialized=json.dumps(audit)
        for private in (receipt,'998900012345','TEST private incoming reference','TEST recipient'):
            self.assertNotIn(private,serialized)
        original=wallet.audit_read
        def fail(*args,**kwargs):
            original(*args,**kwargs)
            raise RuntimeError('TEST private audit failure')
        for suffix in routes:
            with patch.object(wallet,'audit_read',side_effect=fail):
                response=self.req(prefix+suffix,admin=True,expected=500)
            self.assertEqual(set(response),{'error'})
            self.assertNotIn('TEST private',json.dumps(response))
            self.assertNotIn(receipt,json.dumps(response))
            self.assertEqual(records(),audit)
        for suffix in ('/history?before=0&before=1','/history?before=','/history?unknown=1',
                       '/history/0/receipt?before=1','/receipt?unknown=1'):
            self.req(prefix+suffix,admin=True,expected=400)
        self.req('/api/admin/topups/'+'0'*32+'/receipt',admin=True,expected=404)
        self.assertEqual(records(),audit)
        self.assertEqual(financial_snapshot(),before)


if __name__=='__main__':unittest.main()
