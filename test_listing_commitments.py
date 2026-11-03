"""Listing changes must not invalidate care already promised to a customer."""
import copy
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import catalog
import server
import booking_engine as engine
import test_booking_engine


class ListingCommitmentTests(unittest.TestCase):
    setUp=test_booking_engine.BookingEngineTests.setUp
    save=test_booking_engine.BookingEngineTests.save
    review=test_booking_engine.BookingEngineTests.review
    quote=test_booking_engine.BookingEngineTests.quote
    request=test_booking_engine.BookingEngineTests.request
    act=test_booking_engine.BookingEngineTests.act

    def reject(self,data,revision=2):
        with self.assertRaises(catalog.CatalogError) as caught:self.save(data,revision)
        self.assertEqual(caught.exception.status,409)
        with server.db() as con:self.assertEqual(catalog.revision(con,'abc'),revision)

    def test_capacity_housing_and_location_cannot_break_accepted_care(self):
        booking=self.act(self.request(self.quote(pets=['cat-a','cat-b'])))
        for field,value in [('capacity',1),('location',{'lat':41.4,'lon':69.3,'address':'NEW TEST address'})]:
            data=copy.deepcopy(self.listing);data['listings'][0][field]=value
            self.reject(data)
        data=copy.deepcopy(self.listing);data['housing']='apartment';data['listings'][0]['capacity']=1
        self.reject(data)
        for changed in [None,{**self.account['sitterProfile'],'housing':'apartment'}]:
            with server.db() as con:
                con.execute('BEGIN IMMEDIATE')
                with self.assertRaises(catalog.CatalogError):
                    catalog.invalidate_profile(con,'abc',self.account,{**self.account,'sitterProfile':changed})
        with server.db() as con:
            self.assertEqual(engine.view(con,booking['id'],'abc')['snapshot'],booking['snapshot'])

    def test_pause_archive_and_price_edit_preserve_agreement_and_completion(self):
        booking=self.act(self.request())
        data=copy.deepcopy(self.listing);data['listings'][0].update(price=999999,active=False)
        self.save(data,2)
        with server.db() as con:
            catalog.archive(con,'abc','boarding',3)
        self.save({'housing':'house','listings':[]},4)
        with server.db() as con:
            detail=engine.view(con,booking['id'],'abc')
            self.assertEqual(detail['snapshot'],booking['snapshot'])
            self.assertEqual(detail['status'],'accepted')
        booking=self.act(booking,'start',user='customer',now=self.start)
        booking=self.act(booking,'start',now=self.start)
        booking=self.act(booking,'complete',user='customer',now=self.end)
        booking=self.act(booking,'complete',now=self.end)
        self.assertEqual(booking['status'],'completed')
        moved=copy.deepcopy(self.listing);moved['housing']='apartment';moved['listings'][0]['capacity']=1
        moved['listings'][0]['location']['address']='AFTER COMPLETION'
        self.save(moved,5)

    def test_capacity_uses_peak_not_sum_and_readded_listing_still_checks_obligations(self):
        first=self.act(self.request(self.quote(end=self.start+timedelta(days=1))))
        self.act(self.request(self.quote(user='other',start=self.start+timedelta(days=1)),user='other'))
        data=copy.deepcopy(self.listing);data['listings'][0]['capacity']=1
        self.save(data,2)  # Adjacent intervals, one animal at any instant.
        self.save({'housing':'house','listings':[]},3)
        data['listings'][0]['location']['address']='REPLACEMENT'
        self.reject(data,4)
        with server.db() as con:self.assertEqual(engine.view(con,first['id'],'abc')['status'],'accepted')

    def test_acceptance_and_capacity_reduction_share_one_write_lock(self):
        booking=self.request(self.quote(pets=['cat-a','cat-b']))
        data=copy.deepcopy(self.listing);data['listings'][0]['capacity']=1
        gate=threading.Barrier(2)
        def run(action):
            gate.wait()
            try:
                if action=='accept':self.act(booking)
                else:self.save(data,2)
                return action
            except (catalog.CatalogError,engine.BookingError):return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,['accept','reduce']))
        self.assertEqual(results.count('conflict'),1)
        with server.db() as con:
            cap=json.loads(con.execute("SELECT data FROM listings WHERE user_id='abc'").fetchone()[0])['listings'][0]['capacity']
            status=con.execute('SELECT status FROM bookings WHERE id=?',(booking['id'],)).fetchone()[0]
            self.assertFalse(cap==1 and status=='accepted')


if __name__=='__main__':unittest.main()
