import csv
from datetime import datetime,timedelta,timezone
from io import StringIO
import json
import secrets
import unittest
from urllib.request import Request,urlopen

import admin_metrics
import server
import wallet
import test_admin_bookings as fixtures
import test_operator_access


class AdminMetricsTests(unittest.TestCase):
    setUp=fixtures.AdminBookingTests.setUp
    save=fixtures.AdminBookingTests.save
    review=fixtures.AdminBookingTests.review
    stop_http=fixtures.AdminBookingTests.stop_http
    req=fixtures.AdminBookingTests.req
    admin=fixtures.AdminBookingTests.admin
    as_role=test_operator_access.OperatorAccessTests.as_role

    def seed_metrics(self):
        current=datetime.now(timezone.utc)
        with server.db() as con:
            con.execute('BEGIN IMMEDIATE')
            for amount,kind in ((100000,'topup'),(-10000,'commission'),(2000,'commission_refund'),(-5000,'topup_correction')):
                wallet.post_entry(con,'abc',amount,kind,'PRIVATE TEST source:'+kind,'PRIVATE TEST actor','PRIVATE TEST reason')
            con.execute("INSERT INTO topup_requests(id,user_id,amount_minor,receipt,receipt_hash,qr_version,terms_version,request_id,status,created) VALUES(?,?,?,?,?,1,'TEST','TEST request','pending',?)",
                (secrets.token_hex(16),'abc',1000,'PRIVATE TEST receipt','PRIVATE TEST hash',(current-timedelta(days=1)).isoformat()))
            for status,days in (('open',2),('waiting_user',10),('resolved',30)):
                created=(current-timedelta(days=days)).isoformat()
                identity=secrets.token_hex(16)
                con.execute('INSERT INTO support_tickets(id,owner_id,subject,topic,status,revision,created,updated) VALUES(?,?,?,?,?,0,?,?)',
                    (identity,'customer','PRIVATE TEST subject','general',status,created,created))
                if status=='waiting_user':
                    reply=(current-timedelta(days=days)+timedelta(seconds=120)).isoformat()
                    con.execute('UPDATE support_tickets SET revision=1,updated=? WHERE id=?',(reply,identity))
                    con.execute("INSERT INTO support_messages(ticket_id,revision,actor,author_role,action,text,created) VALUES(?,1,'TEST operator','support','reply','PRIVATE TEST reply',?)",(identity,reply))
        return current

    def test_exact_balances_queue_age_and_export_never_include_private_rows(self):
        current=self.seed_metrics()
        with server.db() as con:report=admin_metrics.snapshot(con,'administrator',current)
        self.assertEqual(report['wallet'],{'topupCreditedMinor':'100000','commissionDebitedMinor':'10000','commissionRefundedMinor':'2000','correctionDebitedMinor':'5000','totalBalanceMinor':'100087000'})
        self.assertEqual(report['topups'],{'pending':1,'needs_info':0,'approved':0,'rejected':0})
        self.assertEqual(report['support'],{'open':1,'waiting_user':1,'resolved':1})
        self.assertEqual(report['oldestOpenSupportSeconds'],172800)
        self.assertEqual(report['oldestPendingTopupSeconds'],86400)
        self.assertEqual(report['respondedSupportTickets'],1)
        self.assertEqual(report['averageSupportFirstResponseSeconds'],120)
        self.assertNotIn('PRIVATE',json.dumps(report))
        rows=list(csv.DictReader(StringIO(admin_metrics.export(report).decode('utf-8-sig'))))
        self.assertEqual(next(row for row in rows if row['metric']=='wallet.commissionRefundedMinor')['value'],'2000')
        self.assertNotIn('PRIVATE',json.dumps(rows))
        with server.db() as con:limited=admin_metrics.snapshot(con,'finance',current)
        for key in ('bookings','support','disputes','oldestOpenSupportSeconds','overdueDisputes','respondedSupportTickets','averageSupportFirstResponseSeconds'):self.assertNotIn(key,limited)
        self.assertNotIn('support.',admin_metrics.export(limited).decode('utf-8-sig'))

    def test_csv_http_is_private_audited_read_only_and_role_scoped(self):
        self.seed_metrics()
        for path in ('/api/admin/metrics','/api/admin/metrics.csv'):self.req(path,status=401)
        for role in ('support','moderation'):
            self.as_role(role)
            self.admin('/api/admin/metrics',status=403);self.admin('/api/admin/metrics.csv',status=403)
        self.as_role('finance')
        self.assertEqual(self.admin('/api/admin/metrics')['scope'],'finance')
        request=Request(self.base+'/api/admin/metrics.csv',headers={'Cookie':'momiq_admin='+self.admin_token})
        with urlopen(request) as response:
            self.assertEqual(response.status,200)
            self.assertEqual(response.headers['Cache-Control'],'no-store')
            self.assertEqual(response.headers['X-Content-Type-Options'],'nosniff')
            self.assertIn('attachment;',response.headers['Content-Disposition'])
            content=response.read().decode('utf-8-sig')
        self.assertNotIn('PRIVATE',content);self.assertNotIn('support.',content);self.assertNotIn('bookings.',content)
        self.admin('/api/admin/metrics?scope=administrator',status=400)
        self.admin('/api/admin/metrics','POST',status=403)
        self.as_role('administrator');self.admin('/api/admin/metrics','POST',status=405)
        self.assertIn('support',self.admin('/api/admin/metrics'))
        with server.db() as con:
            rows=con.execute("SELECT actor,action,target FROM audit WHERE action LIKE 'metrics-%' ORDER BY id").fetchall()
            self.assertEqual([tuple(row) for row in rows],[('TEST operator','metrics-read','finance:all_time'),('TEST operator','metrics-export','finance:all_time'),('TEST operator','metrics-read','administrator:all_time')])
            self.assertEqual(con.execute('SELECT COUNT(*) FROM wallet_entries').fetchone()[0],4)

    def test_empty_queue_has_no_invented_age_and_csv_keeps_integer_minor_units(self):
        with server.db() as con:report=admin_metrics.snapshot(con,'finance',datetime.now(timezone.utc))
        self.assertIsNone(report['oldestPendingTopupSeconds'])
        report['wallet']['totalBalanceMinor']='9007199254740993'
        text=admin_metrics.export(report).decode('utf-8-sig')
        self.assertIn('wallet.totalBalanceMinor,9007199254740993,UZS_minor,',text)


if __name__=='__main__':unittest.main()
