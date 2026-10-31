import json
import unittest
from urllib.parse import urlencode

import server
import test_admin_bookings as fixtures


class AdminAccountTests(unittest.TestCase):
    setUp=fixtures.AdminBookingTests.setUp
    save=fixtures.AdminBookingTests.save
    review=fixtures.AdminBookingTests.review
    stop_http=fixtures.AdminBookingTests.stop_http
    req=fixtures.AdminBookingTests.req
    admin=fixtures.AdminBookingTests.admin

    def seed_accounts(self):
        with server.db() as con:
            template=json.loads(con.execute("SELECT account FROM users WHERE id='abc'").fetchone()[0])
            data=con.execute("SELECT data FROM listings WHERE user_id='abc'").fetchone()[0]
            for n in range(24):
                uid=f'{n:024x}'
                account=json.loads(json.dumps(template));account['profile']['first']=f'TEST {n:02}'
                account['addresses']=[{'id':'private','address':'PRIVATE ADDRESS','lat':41.3,'lon':69.2}]
                account['pets']=[{'id':'private-pet','type':'Mushuk','name':'PRIVATE PET'}]
                con.execute('INSERT INTO users VALUES(?,?,?,?,?)',(uid,f'99890999{n:04}',json.dumps(account),n%2,server.now()))
                con.execute("INSERT INTO user_roles VALUES(?,'sitter')",(uid,))
                con.execute('INSERT INTO listings VALUES(?,?,?)',(uid,data,server.now()))

    def test_index_metadata_paging_filters_and_private_detail_audit(self):
        self.seed_accounts()
        self.req('/api/admin/users',status=401)
        first=self.admin('/api/admin/users?role=sitter')
        second=self.admin('/api/admin/users?role=sitter&'+urlencode({'after':first['nextCursor']}))
        self.assertEqual(len(first['users']),20)
        self.assertEqual(len(second['users']),6)
        ids=[x['id'] for x in first['users']+second['users']]
        self.assertEqual(ids,sorted(set(ids)))
        self.assertNotIn('PRIVATE',json.dumps(first))
        self.assertNotIn('addresses',first['users'][0]['account'])
        self.assertIsNone(first['users'][0]['account']['profile']['photo'])
        found=self.admin('/api/admin/users?role=sitter&status=blocked&q=TEST+23')['users']
        self.assertEqual(len(found),1)
        uid=found[0]['id'];path='/api/admin/users/'+uid
        self.req(path,status=401)
        detail=self.admin(path)['user']
        self.assertEqual(detail['account']['addresses'][0]['address'],'PRIVATE ADDRESS')
        self.assertIn('_revision',detail['account'])
        with server.db() as con:
            self.assertEqual(con.execute("SELECT actor,target FROM audit WHERE action='admin-users-read'").fetchone()[:],('TEST operator',uid))
        self.assertEqual(self.admin('/api/admin/users?q=PRIVATE')['users'],[])
        self.admin('/api/admin/users?role=customer&'+urlencode({'after':first['nextCursor']}),status=400)
        for query in ['role=admin','q=a&q=b','after=bogus','status=pending','service=boarding','unknown=1']:
            self.admin('/api/admin/users?'+query,status=400)

    def test_listing_index_and_detail_use_actual_moderation_without_bulk_addresses(self):
        self.seed_accounts()
        first=self.admin('/api/admin/listings?status=pending&service=boarding')
        self.assertEqual(len(first['listings']),20)
        self.assertNotIn('location',first['listings'][0])
        self.assertNotIn('PRIVATE',json.dumps(first))
        second=self.admin('/api/admin/listings?status=pending&service=boarding&'+urlencode({'after':first['nextCursor']}))
        self.assertEqual(len(second['listings']),4)
        self.assertIsNone(second['nextCursor'])
        entry=first['listings'][0]
        path='/api/admin/listings/'+entry['userId']+'/boarding'
        self.req(path,status=401)
        detail=self.admin(path)['listing']
        self.assertIn('PRIVATE STREET',detail['location']['address'])
        self.assertEqual(detail['moderation']['status'],'pending')
        self.assertIn('_revision',detail)
        self.assertEqual(self.admin('/api/admin/listings?status=approved')['listings'][0]['userId'],'abc')
        with server.db() as con:
            self.assertEqual(con.execute("SELECT actor,target FROM audit WHERE action='admin-listings-read'").fetchone()[:],('TEST operator',entry['id']))
        for query in ['role=sitter','status=blocked','service=other','after=W10']:
            self.admin('/api/admin/listings?'+query,status=400)
