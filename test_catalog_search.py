import copy
from datetime import timedelta
import json
import unittest
from urllib.parse import urlencode

import catalog_search
import catalog
import server
import test_booking_engine as fixtures
import test_booking_http as http_fixtures


class SearchHttpTests(unittest.TestCase):
    setUp=http_fixtures.BookingHttpTests.setUp
    save=http_fixtures.BookingHttpTests.save
    review=http_fixtures.BookingHttpTests.review
    req=http_fixtures.BookingHttpTests.req
    stop_http=http_fixtures.BookingHttpTests.stop_http

    def clones(self):
        with server.db() as con:
            account=json.loads(con.execute("SELECT account FROM users WHERE id='abc'").fetchone()[0])
            listing=json.loads(con.execute("SELECT data FROM listings WHERE user_id='abc'").fetchone()[0])
            for n in range(24):
                uid=f'sitter-{n:02}'
                owner=copy.deepcopy(account);owner['profile']['first']=f'Enaga{n:02}'
                data=copy.deepcopy(listing);data['listings'][0]['price']=10000+n
                con.execute('INSERT INTO users VALUES(?,?,?,0,?)',(uid,f'99890999{n:04}',json.dumps(owner),server.now()))
                con.execute("INSERT INTO user_roles VALUES(?,'sitter')",(uid,))
                con.execute('INSERT INTO wallet_accounts VALUES(?,1500000)',(uid,))
                con.execute('INSERT INTO listings VALUES(?,?,?)',(uid,json.dumps(data),server.now()))
                con.execute("INSERT INTO listing_moderation(user_id,service,status,approved_hash,test_only,reason,public_media) SELECT ?,service,status,?,test_only,reason,public_media FROM listing_moderation WHERE user_id='abc'",(uid,catalog.fingerprint(owner,data['housing'],data['listings'][0])))

    def test_pagination_stable_no_duplicates_and_filter_bound_cursor(self):
        self.clones()
        first=self.req('/api/sitters')
        self.assertEqual(len(first['sitters']),20)
        self.assertIsNotNone(first['nextCursor'])
        cursor=urlencode({'after':first['nextCursor']})
        second=self.req('/api/sitters?'+cursor)
        ids=[s['id'] for s in first['sitters']+second['sitters']]
        self.assertEqual(len(ids),25)
        self.assertEqual(ids,sorted(set(ids)))
        self.assertIsNone(second['nextCursor'])
        # Removal before the cursor cannot shift later rows into duplicates.
        with server.db() as con:con.execute("UPDATE users SET blocked=1 WHERE id='sitter-00'")
        self.assertEqual(self.req('/api/sitters?'+cursor)['sitters'],second['sitters'])
        self.req('/api/sitters?'+cursor+'&pet=dog',status=400)
        self.req('/api/sitters?after=bogus',status=400)
        self.req('/api/sitters?after=W10',status=400)

    def test_filters_favorites_authorization_and_no_private_leaks(self):
        self.clones()
        query={'service':'boarding','pet':'cat','minPrice':'10005','maxPrice':'10008','animals':'2','q':'enaga'}
        found=self.req('/api/sitters?'+urlencode(query))['sitters']
        self.assertEqual([s['price'] for s in found],[10005,10006,10007,10008])
        for extra in [{'service':'personal'},{'pet':'dog'},{'animals':'3'},{'verified':'1'},{'minRating':'4.8'}]:
            self.assertEqual(self.req('/api/sitters?'+urlencode(dict(query,**extra)))['sitters'],[])
        for query in ['animals=0','animals=true','minPrice=2&maxPrice=1','minPrice=NaN','service=other','verified=true','pet=other','q=x&q=y','unknown=1']:
            self.req('/api/sitters?'+query,status=400)
        with server.db() as con:
            account=json.loads(con.execute("SELECT account FROM users WHERE id='customer'").fetchone()[0])
            account['favorites']=['sitter-23:boarding']
            con.execute("UPDATE users SET account=? WHERE id='customer'",(json.dumps(account),))
        favorite=self.req('/api/sitters?favorites=1')['sitters']
        self.assertEqual([s['id'] for s in favorite],['sitter-23:boarding'])
        self.assertEqual(self.req('/api/sitters?favorites=1',user='stranger')['sitters'],[])
        self.tokens['unauthenticated']='invalid'
        self.req('/api/sitters?favorites=1',user='unauthenticated',status=401)
        self.assertNotIn('PRIVATE',json.dumps(found+favorite))


class SearchCapacityTests(unittest.TestCase):
    setUp=fixtures.BookingEngineTests.setUp
    save=fixtures.BookingEngineTests.save
    review=fixtures.BookingEngineTests.review
    quote=fixtures.BookingEngineTests.quote
    request=fixtures.BookingEngineTests.request
    act=fixtures.BookingEngineTests.act
    expect_error=fixtures.BookingEngineTests.expect_error

    def search(self, start=None,end=None,animals=1):
        params={'startsAt':[(start or self.start).isoformat()], 'endsAt':[(end or self.end).isoformat()], 'animals':[str(animals)]}
        with server.db() as con:return catalog_search.page(con,'local',params)['sitters']

    def test_capacity_pending_not_reserved_accepted_peak_and_boundary(self):
        pending=self.request(self.quote(pets=['cat-a']))
        self.assertEqual(self.search(animals=2)[0]['freeCapacity'],2)
        accepted=self.act(pending)
        self.assertEqual(self.search()[0]['freeCapacity'],1)
        self.assertEqual(self.search(animals=2),[])
        after=self.end
        self.assertEqual(self.search(start=after,end=after+timedelta(days=1),animals=2)[0]['freeCapacity'],2)
        self.act(accepted,'cancel',user='customer')
        self.assertEqual(self.search(animals=2)[0]['freeCapacity'],2)

    def test_capacity_uses_peak_not_sum_and_cross_service_block(self):
        first=self.act(self.request(self.quote(end=self.start+timedelta(days=1))))
        self.act(self.request(self.quote(user='other',start=self.start+timedelta(days=1)),user='other'))
        self.assertEqual(self.search()[0]['freeCapacity'],1)
        # Add a second service owned by the same sitter; overlapping care blocks it.
        with server.db() as con:
            raw=json.loads(con.execute("SELECT data FROM listings WHERE user_id='abc'").fetchone()[0])
            personal=copy.deepcopy(raw['listings'][0]);personal.update(type='personal',capacity=None)
            raw['listings'].append(personal)
            account=json.loads(con.execute("SELECT account FROM users WHERE id='abc'").fetchone()[0])
            con.execute("UPDATE listings SET data=? WHERE user_id='abc'",(json.dumps(raw),))
            con.execute("INSERT INTO listing_moderation(user_id,service,status,approved_hash,test_only,public_media) SELECT user_id,'personal',status,?,test_only,public_media FROM listing_moderation WHERE user_id='abc' AND service='boarding'",(catalog.fingerprint(account,raw['housing'],personal),))
        self.assertEqual([s['service'] for s in self.search()],[0])
        self.assertEqual(first['status'],'accepted')
