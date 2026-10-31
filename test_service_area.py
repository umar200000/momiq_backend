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
