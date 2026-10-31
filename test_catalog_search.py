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

    def test_favorite_filter_checks_only_selected_eligible_profiles(self):
        from unittest.mock import patch
        self.clones()
        with server.db() as con:
            for ids, expected in [
                ([], []),
                (['legacy-id', 'sitter-23:boarding', 'sitter-23:boarding'], ['sitter-23:boarding']),
                (['abc:personal'], []),
            ]:
                con.execute("UPDATE users SET account=json_set(account,'$.favorites',json(?)) WHERE id='customer'",
                            (json.dumps(ids),))
                with patch.object(catalog, 'fingerprint', wraps=catalog.fingerprint) as fingerprint:
                    result = catalog_search.page(con, 'local', {'favorites':['1']}, user='customer')
                    self.assertEqual([r['id'] for r in result['sitters']], expected)
                    self.assertEqual(fingerprint.call_count, len(expected))

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

    def test_proximity_orders_all_pages_not_only_first_twenty_and_binds_origin(self):
        self.clones()
        with server.db() as con:
            for n in range(24):
                uid=f'sitter-{n:02}'
                account=json.loads(con.execute('SELECT account FROM users WHERE id=?',(uid,)).fetchone()[0])
                data=json.loads(con.execute('SELECT data FROM listings WHERE user_id=?',(uid,)).fetchone()[0])
                data['listings'][0]['location'].update(lat=41.301234+(23-n)*.01,lon=69.271234)
                con.execute('UPDATE listings SET data=? WHERE user_id=?',(json.dumps(data),uid))
                con.execute('UPDATE listing_moderation SET approved_hash=? WHERE user_id=?',(catalog.fingerprint(account,data['housing'],data['listings'][0]),uid))
        query={'lat':'41.30','lon':'69.27','region':'tashkent','q':'enaga'}
        first=self.req('/api/sitters?'+urlencode(query))
        self.assertEqual(first['sitters'][0]['id'],'sitter-23:boarding')
        self.assertEqual(first['sitters'][0]['distance'],0)
        self.assertTrue(first['sitters'][0]['distanceApproximate'])
        second=self.req('/api/sitters?'+urlencode(dict(query,after=first['nextCursor'])))
        rows=first['sitters']+second['sitters']
        self.assertEqual(len(rows),24)
        self.assertEqual(len({r['id'] for r in rows}),24)
        self.assertEqual([r['distance'] for r in rows],sorted(r['distance'] for r in rows))
        self.assertNotIn('301234',json.dumps(rows))
        self.req('/api/sitters?'+urlencode(dict(query,lat='41.31',after=first['nextCursor'])),status=400)
        self.assertEqual(len(self.req('/api/sitters?'+urlencode(dict(query,maxDistance=1)))['sitters']),1)

    def test_location_validation_manual_region_and_home_visit_has_no_radius(self):
        for query in ['lat=41','lon=69','lat=NaN&lon=69','lat=91&lon=69','lat=41&lon=181',
                      'lat=41&lon=Infinity','region=other','maxDistance=5','lat=41&lon=69&maxDistance=0',
                      'lat=41&lon=69&maxDistance=51','lat=41&lat=42&lon=69']:
            self.req('/api/sitters?'+query,status=400)
        manual=self.req('/api/sitters?region=tashkent')['sitters']
        self.assertTrue(manual)
        self.assertTrue(all(s['distance'] is None for s in manual))
        with server.db() as con:
            data=json.loads(con.execute("SELECT data FROM listings WHERE user_id='abc'").fetchone()[0])
            account=json.loads(con.execute("SELECT account FROM users WHERE id='abc'").fetchone()[0])
            item=copy.deepcopy(data['listings'][0]);item.update(type='homeVisit',location=None,capacity=None)
            data['listings'].append(item)
            con.execute("UPDATE listings SET data=? WHERE user_id='abc'",(json.dumps(data),))
            con.execute("INSERT INTO listing_moderation(user_id,service,status,approved_hash,test_only,public_media) SELECT user_id,'homeVisit',status,?,test_only,public_media FROM listing_moderation WHERE user_id='abc' AND service='boarding'",(catalog.fingerprint(account,data['housing'],item),))
        found=self.req('/api/sitters?service=homeVisit&lat=41.4&lon=69.4&maxDistance=1')['sitters']
        self.assertEqual(len(found),1)
        self.assertIsNone(found[0]['distance'])
        self.assertIsNone(found[0]['location'])

    def test_distance_geometry_and_unknown_location(self):
        self.assertEqual(catalog_search.distance_km([0,0],{'lat':0,'lon':1}),111.2)
        self.assertEqual(catalog_search.distance_km([0,179.9],{'lat':0,'lon':-179.9}),22.2)
        self.assertIsNone(catalog_search.distance_km(None,{'lat':0,'lon':1}))


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
        from unittest.mock import patch
        import booking_capacity
        with patch.object(booking_capacity,'occupancy',wraps=booking_capacity.occupancy) as read_usage:
            self.assertEqual([s['service'] for s in self.search()],[0])
            self.assertEqual(read_usage.call_count,1)
        self.assertEqual(first['status'],'accepted')
