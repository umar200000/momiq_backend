from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import secrets
import threading
import unittest
from unittest.mock import patch

import booking_engine as engine
import booking_worker
import server
import wallet
import test_booking_engine as fixtures


class HandoverTests(unittest.TestCase):
    setUp = fixtures.BookingEngineTests.setUp
    save = fixtures.BookingEngineTests.save
    review = fixtures.BookingEngineTests.review
    quote = fixtures.BookingEngineTests.quote
    request = fixtures.BookingEngineTests.request
    act = fixtures.BookingEngineTests.act
    expect_error = fixtures.BookingEngineTests.expect_error

    def confirm(self, booking, action, user, **kwargs):
        return self.act(booking,action,user,reason='',now=kwargs.pop('now',self.start),**kwargs)

    def start_both(self):
        accepted=self.act(self.request())
        first=self.confirm(accepted,'start','customer')
        return self.confirm(first,'start','abc')

    def test_both_parties_confirm_start_and_early_completion_without_new_fee(self):
        accepted=self.act(self.request()); key=secrets.token_hex(16)
        first=self.confirm(accepted,'start','customer',request=key)
        self.assertEqual(first['status'],'accepted')
        self.assertEqual(first['confirmations']['start'],{'mine':True,'peer':False})
        self.assertEqual(self.confirm(accepted,'start','customer',request=key),first)
        self.expect_error(409,lambda:self.confirm(first,'start','customer'))
        active=self.confirm(first,'start','abc')
        self.assertEqual(active['status'],'active')
        self.assertEqual(active['confirmations']['start'],{'mine':True,'peer':True})
        first_done=self.confirm(active,'complete','abc',now=self.start+timedelta(hours=1))
        self.assertEqual(first_done['status'],'active')
        complete=self.confirm(first_done,'complete','customer',now=self.start+timedelta(hours=1))
        self.assertEqual(complete['status'],'completed')
        self.assertEqual(complete['confirmations']['complete'],{'mine':True,'peer':True})
        self.assertEqual(complete['snapshot']['price'],accepted['snapshot']['price'])
        with server.db() as con:
            self.assertEqual(wallet.balance(con,'abc'),85000000)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM wallet_entries').fetchone()[0],1)
        self.expect_error(409,lambda:self.confirm(complete,'complete','customer'))

    def test_handover_time_ownership_revision_and_dispute_guards(self):
        pending=self.request()
        self.expect_error(409,lambda:self.confirm(pending,'start','customer',now=self.now))
        accepted=self.act(pending)
        self.expect_error(404,lambda:self.confirm(accepted,'start','stranger'))
        self.expect_error(409,lambda:self.confirm(accepted,'start','customer',now=self.start-timedelta(microseconds=1)))
        self.expect_error(409,lambda:self.confirm(accepted,'start','customer',now=self.end))
        self.expect_error(409,lambda:self.confirm(accepted,'complete','customer'))
        first=self.confirm(accepted,'start','customer')
        self.expect_error(409,lambda:self.confirm(accepted,'start','abc'))
        active=self.confirm(first,'start','abc')
        with server.db() as con:
            engine.begin(con)
            engine.change(con,engine.owned(con,active['id'],'customer'),'disputed','admin','dispute','TEST dispute',self.start)
            disputed=engine.view(con,active['id'],'customer')
        self.expect_error(409,lambda:self.confirm(disputed,'complete','customer'))
        self.assertEqual(booking_worker.run_once(server.db,'local',now=self.end+timedelta(days=1)),0)
        with server.db() as con:
            self.assertEqual(engine.view(con,active['id'],'customer')['status'],'disputed')

    def test_parallel_confirmations_do_not_lose_either_party(self):
        accepted=self.act(self.request()); barrier=threading.Barrier(2)
        def start(user):
            barrier.wait()
            try: return self.confirm(accepted,'start',user)
            except engine.BookingError as error:
                self.assertEqual(error.status,409)
                return user
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(start,['customer','abc']))
        first=next(x for x in results if isinstance(x,dict))
        second=next(x for x in results if isinstance(x,str))
        self.assertEqual(self.confirm(first,'start',second)['status'],'active')
        with server.db() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM booking_events WHERE action='start'").fetchone()[0],2)

    def test_unfinished_overdue_care_blocks_new_acceptance_until_both_finish(self):
        active=self.start_both()
        self.now=self.end+timedelta(minutes=1)
        following=self.request(self.quote(user='other',start=self.now+timedelta(days=1),end=self.now+timedelta(days=2)),user='other')
        self.expect_error(409,lambda:self.act(following))
        first=self.confirm(active,'complete','customer',now=self.now)
        self.expect_error(409,lambda:self.act(following))
        self.confirm(first,'complete','abc',now=self.now)
        self.assertEqual(self.act(following)['status'],'accepted')

    def test_failed_confirmation_rolls_back_notice_revision_and_history(self):
        accepted=self.act(self.request())
        with patch.object(engine.notifications,'publish',side_effect=RuntimeError('TEST storage')):
            with self.assertRaises(RuntimeError): self.confirm(accepted,'start','customer')
        with server.db() as con:
            after=engine.view(con,accepted['id'],'customer')
            self.assertEqual(after['revision'],1)
            self.assertEqual(after['confirmations']['start'],{'mine':False,'peer':False})
            self.assertEqual(con.execute("SELECT COUNT(*) FROM booking_events WHERE action='start'").fetchone()[0],0)
