import dataclasses
import unittest
from datetime import datetime, timedelta, timezone

from booking_rules import (AnimalRate, Incident, acceptance_requirement,
                           balance_after_acceptance, cancellation_commission_refund,
                           expired, incidents_for_review, late_cancellation,
                           no_show_review_deadline, no_show_stage, price_snapshot,
                           reply_deadline)


class BookingRuleTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026,10,28,12,tzinfo=timezone(timedelta(hours=5)))
        self.rates = [AnimalRate('cat-one',50_000_000), AnimalRate('cat-two',50_000_000)]
        self.quote = price_snapshot('boarding',self.rates,3,1000,7)

    def test_approved_three_million_example_and_frozen_snapshot(self):
        self.assertEqual(self.quote.service_total_minor,300_000_000)  # 3,000,000 UZS
        self.assertEqual(self.quote.commission_minor,30_000_000)
        self.rates[0] = AnimalRate('cat-one',100)
        self.assertEqual(self.quote.rates[0].daily_minor,50_000_000)
        with self.assertRaises(dataclasses.FrozenInstanceError): self.quote.commission_bps=2000
        next_quote=price_snapshot('boarding',self.rates,3,2000,8)
        self.assertEqual(next_quote.settings_version,8)
        self.assertEqual(self.quote.settings_version,7)

    def test_personal_limit_duplicate_animal_and_invalid_numbers(self):
        with self.assertRaises(ValueError): price_snapshot('personal',self.rates,1,1000,1)
        with self.assertRaises(ValueError): price_snapshot('boarding',[self.rates[0]]*2,1,1000,1)
        for bad in [True,1.5,0,-1,367]:
            with self.assertRaises(ValueError): price_snapshot('boarding',self.rates,bad,1000,1)
        for bad in [True,-1,10001,10.5]:
            with self.assertRaises(ValueError): price_snapshot('boarding',self.rates,1,bad,1)
        with self.assertRaises(ValueError): price_snapshot('boarding',[AnimalRate('cat',100_000_000_000)],2,1000,1)

    def test_commission_rounds_once_at_total_and_zero_percent_is_valid(self):
        quote=price_snapshot('boarding',[AnimalRate('a',5),AnimalRate('b',5)],1,1000,1)
        self.assertEqual(quote.commission_minor,1)  # not 1+1 rounded per animal
        self.assertEqual(price_snapshot('boarding',[AnimalRate('a',5)],1,1000,1).commission_minor,1)
        self.assertEqual(price_snapshot('personal',[AnimalRate('a',5)],1,0,1).commission_minor,0)
        self.assertEqual(price_snapshot('personal',[AnimalRate('a',99)],1,10000,1).commission_minor,99)

    def test_acceptance_uses_maximum_of_balance_threshold_and_commission(self):
        self.assertEqual(acceptance_requirement(self.quote),30_000_000)
        with self.assertRaises(ValueError): balance_after_acceptance(20_000_000,self.quote)
        self.assertEqual(balance_after_acceptance(30_000_000,self.quote),0)
        small=price_snapshot('homeVisit',[AnimalRate('a',100_000)],1,1000,1)
        with self.assertRaises(ValueError): balance_after_acceptance(1_499_999,small)
        self.assertEqual(balance_after_acceptance(1_500_000,small),1_490_000)
        zero=price_snapshot('homeVisit',[AnimalRate('a',100_000)],1,0,1)
        with self.assertRaises(ValueError): balance_after_acceptance(0,zero)

    def test_reply_deadline_and_timezone_boundaries(self):
        start=self.now+timedelta(hours=1)
        deadline=reply_deadline(self.now,start)
        self.assertEqual(deadline,start.astimezone(timezone.utc))
        self.assertFalse(expired(deadline,deadline-timedelta(microseconds=1)))
        self.assertTrue(expired(deadline,deadline))
        self.assertEqual(reply_deadline(self.now,self.now+timedelta(days=1)),(self.now+timedelta(hours=2)).astimezone(timezone.utc))
        with self.assertRaises(ValueError): reply_deadline(self.now,self.now)
        with self.assertRaises(ValueError): reply_deadline(self.now.replace(tzinfo=None),start)

    def test_cancellation_is_commission_only_and_never_auto_refunds_after_start(self):
        start=self.now+timedelta(days=2)
        self.assertFalse(late_cancellation(start,start-timedelta(hours=24)))
        self.assertTrue(late_cancellation(start,start-timedelta(hours=24)+timedelta(microseconds=1)))
        self.assertEqual(cancellation_commission_refund(self.quote,'pending',start,self.now),0)
        self.assertEqual(cancellation_commission_refund(self.quote,'accepted',start,self.now),30_000_000)
        self.assertIsNone(cancellation_commission_refund(self.quote,'accepted',start,start))
        self.assertIsNone(cancellation_commission_refund(self.quote,'active',start,start+timedelta(minutes=1)))
        with self.assertRaises(ValueError): cancellation_commission_refund(self.quote,'cancelled',start,self.now)

    def test_no_show_windows_do_not_apply_to_started_service(self):
        for minutes,stage in [(14,'waiting'),(15,'contact_reminder'),(29,'contact_reminder'),(30,'complaint_available')]:
            self.assertEqual(no_show_stage(self.now,self.now+timedelta(minutes=minutes),service_started=False),stage)
        self.assertEqual(no_show_stage(self.now,self.now+timedelta(hours=5),service_started=True),'not_applicable')
        self.assertEqual(no_show_review_deadline(self.now),(self.now+timedelta(hours=48)).astimezone(timezone.utc))

    def test_incident_review_deduplicates_bookings_and_accounts_for_emergencies(self):
        cases=[Incident('a',self.now,'late_cancellation',True,False),Incident('a',self.now,'no_show',True,False),
               Incident('b',self.now-timedelta(days=30),'no_show',True,False),
               Incident('old',self.now-timedelta(days=30,microseconds=1),'no_show',True,False),
               Incident('unconfirmed',self.now,'no_show',False,False),
               Incident('emergency',self.now,'no_show',True,True),
               Incident('future',self.now+timedelta(seconds=1),'no_show',True,False)]
        self.assertEqual(incidents_for_review(cases,self.now),{'bookingIds':['a','b'],'reviewRequired':False})
        cases.append(Incident('c',self.now,'late_cancellation',True,False))
        self.assertTrue(incidents_for_review(cases,self.now)['reviewRequired'])
