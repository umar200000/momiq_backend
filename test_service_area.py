from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import service_area
import server
import test_booking_http


def geometry(root, value):
    path = Path(root)/'test-area.json'
    raw = json.dumps(value).encode()
    path.write_bytes(raw)
    return service_area.load({'MOMIQ_AREA_FILE': str(path), 'MOMIQ_AREA_SHA256': hashlib.sha256(raw).hexdigest()})


class AreaTests(unittest.TestCase):
    def test_city_and_region_limits_and_hosted_configuration(self):
        path = Path(__file__).resolve().parent/'fixtures/tashkent-city-region-qa.geojson'
        # The reviewed city and surrounding province share an edge. Their union
        # is one polygon; concatenating their rings into a MultiPolygon is invalid.
        self.assertEqual(json.loads(path.read_bytes())['geometry']['type'], 'Polygon')
        env = {'MOMIQ_AREA_FILE':str(path),'MOMIQ_AREA_SHA256':hashlib.sha256(path.read_bytes()).hexdigest()}
        area = service_area.load(env)
        for lon,lat,expected in ((69.2797,41.3112,True),(69.5822,41.4689,True),(70.1436,41.0167,True),
                                 (66.9749,39.6542,False),(69.59,42.32,False)):
            self.assertEqual(service_area.contains(area,lon,lat),expected)
        for mode in ('staging','production'):
            with self.assertRaisesRegex(ValueError,'QA service area'):
                service_area.load({**env,'MOMIQ_ENV':mode})
        with tempfile.TemporaryDirectory() as tmp:
            # A digest match alone does not validate the product's release scope.
            p=Path(tmp)/'area.json'
            for box,valid in [((69.2,41.2,69.4,41.4),False),((60,35,75,45),False),((69,40,71,42),True)]:
                x,y,X,Y=box
                p.write_text(json.dumps({'type':'Polygon','coordinates':[[[x,y],[X,y],[X,Y],[x,Y],[x,y]]]}))
                settings={'MOMIQ_ENV':'production','MOMIQ_AREA_FILE':str(p),'MOMIQ_AREA_SHA256':hashlib.sha256(p.read_bytes()).hexdigest()}
                if valid:
                    self.assertIsNotNone(service_area.load(settings))
                else:
                    with self.assertRaisesRegex(ValueError,'Tashkent region'):service_area.load(settings)

    def test_edges_holes_islands_and_bad_configuration(self):
        square = [[0,0],[4,0],[4,4],[0,4],[0,0]]
        hole = [[1,1],[2,1],[2,2],[1,2],[1,1]]
        island = [[5,0],[6,0],[5,1],[5,0]]
        with tempfile.TemporaryDirectory() as tmp:
            area = geometry(tmp, {'type':'MultiPolygon','coordinates':[[square,hole],[island]]})
            for x,y in ((0,0),(3,2),(1,1.5),(5.1,.2),(5.5,.5)):
                service_area.require(area,{'lon':x,'lat':y},'test')
            for x,y in ((1.5,1.5),(4.1,2),(5.6,.6),(-.1,0)):
                with self.assertRaises(service_area.OutsideArea):
                    service_area.require(area,{'lon':x,'lat':y},'test')
            with self.assertRaises(ValueError):
                geometry(tmp,{'type':'Polygon','coordinates':[square[:-1]]})
            with self.assertRaises(ValueError):
                service_area.load({'MOMIQ_AREA_FILE':str(Path(tmp)/'test-area.json'),'MOMIQ_AREA_SHA256':'0'*64})
            with self.assertRaises(service_area.AreaUnavailable):
                service_area.require(None,{'lon':3,'lat':2},'production')


class AreaHttpTests(unittest.TestCase):
    setUp = test_booking_http.BookingHttpTests.setUp
    save,review,stop_http,req = test_booking_http.BookingHttpTests.save,test_booking_http.BookingHttpTests.review,test_booking_http.BookingHttpTests.stop_http,test_booking_http.BookingHttpTests.req
    quote,book = test_booking_http.BookingHttpTests.quote,test_booking_http.BookingHttpTests.book

    def test_preview_uses_combined_boundary_for_address_changes(self):
        path=Path(__file__).resolve().parent/'fixtures/tashkent-city-region-qa.geojson'
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        settings=server.Settings.load({'MOMIQ_ENV':'test','MOMIQ_AREA_FILE':str(path),
                                      'MOMIQ_AREA_SHA256':digest},Path(server.ROOT))
        with patch.object(server,'SETTINGS',settings):
            self.assertEqual(self.req('/api/health')['serviceAreaSha256'],digest)
            account=self.req('/api/me',user='stranger')['account']
            account['profile'].update(first='TEST',last='Owner')
            for lon,lat in ((69.2797,41.3112),(69.5822,41.4689)):
                account['addresses']=[{'id':'home','label':'TEST','address':'TEST','apartment':'','lat':lat,'lon':lon}]
                account=self.req('/api/me','PUT',account,user='stranger')['account']
            account['addresses'][0].update(lon=66.9749,lat=39.6542)
            self.req('/api/me','PUT',account,user='stranger',status=400)
            stored=self.req('/api/me',user='stranger')['account']
            self.assertEqual(stored['addresses'][0]['lon'],69.5822)
            self.assertEqual(stored['_revision'],account['_revision'])

    def test_area_change_blocks_only_new_obligations_and_preserves_private_history(self):
        booked = self.book()
        accepted = self.req('/api/bookings/'+booked['id']+'/accept','POST',
                            {'revision':0,'requestId':'a'*32},user='abc')
        pending = self.book()
        quote = self.quote()
        with tempfile.TemporaryDirectory() as tmp:
            area = geometry(tmp,{'type':'Polygon','coordinates':[[[0,0],[2,0],[2,2],[0,2],[0,0]]]})
            with patch.object(server,'SETTINGS',replace(server.SETTINGS,area=area)):
                self.req('/api/bookings/quotes','POST',self.payload,status=400)
                self.req('/api/bookings','POST',{'quoteId':quote['id'],'requestId':'b'*32},status=400)
                self.req('/api/bookings/'+pending['id']+'/accept','POST',{'revision':0,'requestId':'c'*32},user='abc',status=400)
                prior = self.req('/api/bookings/'+booked['id'])
                self.assertEqual(prior['snapshot']['address'],accepted['snapshot']['address'])
                data = self.req('/api/me',user='stranger')['account']
                data['profile'].update(first='TEST',last='owner')
                data['addresses']=[{'id':'new','label':'TEST','address':'TEST address','apartment':'','lat':41,'lon':69}]
                self.req('/api/me','PUT',data,user='stranger',status=400)
                self.assertEqual(self.req('/api/me',user='stranger')['account']['_revision'],data['_revision'])
                data['addresses'][0].update(lat=1,lon=1)
                result = self.req('/api/me','PUT',data,user='stranger')
                self.assertEqual(result['account']['addresses'][0]['lon'],1)
