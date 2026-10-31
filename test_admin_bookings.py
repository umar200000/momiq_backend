import hashlib
import json
import secrets
import time
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import test_booking_http as http_tests
import server


class AdminBookingTests(unittest.TestCase):
    save=http_tests.BookingHttpTests.save
    review=http_tests.BookingHttpTests.review
    stop_http=http_tests.BookingHttpTests.stop_http
    req=http_tests.BookingHttpTests.req
    quote=http_tests.BookingHttpTests.quote
    book=http_tests.BookingHttpTests.book

    def setUp(self):
        http_tests.BookingHttpTests.setUp(self)
        self.admin_token=secrets.token_hex(32)
        with server.db() as con:
            con.execute("INSERT INTO admins VALUES('TEST operator','TEST salt','disabled')")
            con.execute("INSERT OR IGNORE INTO admin_permissions VALUES('TEST operator','administrator',1)")
            con.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(self.admin_token.encode()).hexdigest(),'TEST operator','admin',time.time()+3600))

    def admin(self,path,method='GET',status=200):
        request=Request(self.base+path,method=method,headers={'Cookie':'momiq_admin='+self.admin_token})
        try:response=urlopen(request)
        except HTTPError as e:response=e
        with response:
            self.assertEqual(response.status,status)
            self.assertEqual(response.headers['Cache-Control'],'no-store')
            return json.load(response)

    def test_private_read_only_details_history_and_care_are_audited(self):
        booking=self.book();identity=booking['id'];path='/api/admin/bookings/'+identity
        self.req(path,status=401)
        self.req('/api/admin/bookings',user='abc',status=401)
        page=self.admin(path)
        self.assertTrue(page['readOnly']);self.assertNotIn('myRole',page)
        self.assertEqual(page['service'],'boarding')
        self.assertEqual(page['commissionEntries'],[])
        self.assertEqual(page['snapshot']['address'],{'address':'Toshkent'})
        self.assertEqual(len(page['history']['items']),1)
        self.assertEqual(self.admin(path+'/care')['items'],[])
        self.assertEqual(self.admin(path+'/history')['items'][0]['action'],'request')
        for method in ('POST','PUT','DELETE'):self.admin(path,method,status=405)
        self.admin('/api/admin/bookings/'+'0'*32,status=404)
        with server.db() as con:
            self.assertEqual(con.execute('SELECT revision,status FROM bookings WHERE id=?',(identity,)).fetchone()[:],(0,'pending'))
            self.assertEqual(con.execute('SELECT COUNT(*) FROM wallet_entries').fetchone()[0],0)
            rows=con.execute("SELECT actor,action,target FROM audit WHERE action LIKE 'admin-booking-%'").fetchall()
            self.assertEqual(len(rows),3)
            self.assertTrue(all(r['actor']=='TEST operator' and r['target']==identity for r in rows))
        self.req('/api/bookings/'+identity+'/accept','POST',{'revision':0,'requestId':secrets.token_hex(16)},user='abc')
        payload={'petId':'owned','kind':'instructions','day':'','category':'','revision':0,
                 'requestId':secrets.token_hex(16),'payload':{'food':'TEST private care','water':'','walk':'','medicine':'','other':'','reason':'TEST update'}}
        self.req('/api/bookings/'+identity+'/care','POST',payload)
        with server.db() as con:con.execute("UPDATE users SET blocked=1 WHERE id='customer'")
        care=self.admin(path+'/care')
        self.assertEqual(care['items'][0]['payload']['food'],'TEST private care')
        detail=self.admin(path)
        self.assertEqual(len(detail['commissionEntries']),1)
        self.assertEqual(detail['commissionEntries'][0]['kind'],'commission')
        self.assertEqual(detail['status'],'accepted')

    def test_pages_are_stable_search_excludes_private_fields_and_filters_are_strict(self):
        for i in range(22):
            if i==20:
                with server.db() as con:con.execute("DELETE FROM attempts WHERE key LIKE 'conversation:booking_%'")
            self.book()
        first=self.admin('/api/admin/bookings?status=pending')
        second=self.admin('/api/admin/bookings?status=pending&before='+first['nextCursor'])
        self.assertEqual(len(first['items']),20);self.assertEqual(len(second['items']),2)
        self.assertFalse({x['id'] for x in first['items']} & {x['id'] for x in second['items']})
        self.assertNotIn('PRIVATE STREET',json.dumps(first));self.assertNotIn('snapshot',first['items'][0])
        self.assertEqual(len(self.admin('/api/admin/bookings?q='+first['items'][0]['id'])['items']),1)
        self.assertEqual(self.admin('/api/admin/bookings?q=PRIVATE')['items'],[])
        for query in ['?before=','?before=-1','?status=invalid','?q=a&q=b','?unknown=1']:
            self.admin('/api/admin/bookings'+query,status=400)


if __name__=='__main__':unittest.main()
