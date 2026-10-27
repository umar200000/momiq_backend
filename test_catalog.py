import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import catalog
import server
from test_media import fixture_image


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = patch.object(server, 'DATA', Path(self.temp.name))
        self.path.start(); self.addCleanup(self.path.stop)
        server.setup()
        self.account = server.default_account()
        self.account['profile'] = {'first':'Test','last':'Enaga','photo':fixture_image()}
        self.account['sitterProfile'] = {'years':1,'about':'TEST ONLY','homePhotos':[fixture_image()], 'housing':'house'}
        self.listing = {'housing':'house','listings':[{'type':'boarding','pets':['cat'],'price':500000,'capacity':2,'active':True,
                       'location':{'lat':41.31234,'lon':69.23456,'address':'PRIVATE STREET 123'}}]}
        with server.db() as con:
            con.execute('INSERT INTO users VALUES(?,?,?,0,?)',('abc','998900123456',json.dumps(self.account),server.now()))
            con.execute("INSERT INTO user_roles VALUES('abc','sitter')")
            con.execute("INSERT INTO wallet_accounts VALUES('abc',1500000)")

    def save(self, data=None, revision=0):
        with server.db() as con:
            return catalog.save(con,'abc',data or self.listing,revision)

    def review(self, revision=1, decision='approve', environment='local', test=True):
        with server.db() as con:
            return catalog.review(con,'abc','boarding',{'decision':decision,'reason':'TEST review','testOnly':test,'_revision':revision},'admin',environment)

    def public(self, environment='local'):
        with server.db() as con:
            con.execute('BEGIN')
            return catalog.profiles(con,environment)

    def test_review_required_and_public_address_is_approximate(self):
        self.save()
        self.assertEqual(self.public(),[])
        self.review()
        [entry]=self.public()
        self.assertEqual(entry['id'],'abc:boarding')
        self.assertEqual(entry['price'],500000)
        self.assertEqual(entry['priceUnit'],'animal_day')
        self.assertEqual(entry['location'],{'lat':41.31,'lon':69.23,'address':'Toshkent'})
        self.assertFalse(entry['identityVerified'])
        self.assertNotIn('PRIVATE',json.dumps(entry))
        self.assertEqual(self.public('production'),[])

    def test_balance_threshold_and_blocking_reversible_without_reapproval(self):
        self.save();self.review()
        for amount,count in [(1499900,0),(1500000,1),(1500100,1)]:
            with server.db() as con: con.execute("UPDATE wallet_accounts SET balance_minor=? WHERE user_id='abc'",(amount,))
            self.assertEqual(len(self.public()),count)
        with server.db() as con: con.execute("UPDATE users SET blocked=1 WHERE id='abc'")
        self.assertEqual(self.public(),[])
        with server.db() as con:
            self.assertIn('abc:boarding',catalog.known_names(con))

    def test_stale_save_or_admin_review_rolls_back(self):
        self.save()
        with self.assertRaises(catalog.CatalogError) as caught: self.save(revision=0)
        self.assertEqual(caught.exception.status,409)
        self.review()
        with self.assertRaises(catalog.CatalogError): self.review(revision=1,decision='reject')
        with server.db() as con:
            self.assertEqual(catalog.document(con,'abc')['_revision'],2)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM audit WHERE action='listing-reject'").fetchone()[0],0)
        self.assertEqual(len(self.public()),1)

    def test_edits_invalidate_approval_but_notifications_do_not(self):
        self.save();self.review()
        after=copy.deepcopy(self.account);after['notifications']={'push':False}
        with server.db() as con:
            catalog.invalidate_profile(con,'abc',self.account,after)
            con.execute("UPDATE users SET account=? WHERE id='abc'",(json.dumps(after),))
        self.assertEqual(len(self.public()),1)
        edited=copy.deepcopy(after);edited['profile']['first']='Changed'
        with server.db() as con:
            catalog.invalidate_profile(con,'abc',after,edited)
            con.execute("UPDATE users SET account=? WHERE id='abc'",(json.dumps(edited),))
        self.assertEqual(self.public(),[])
        with self.assertRaises(catalog.CatalogError): self.review(revision=2)
        self.review(revision=3)
        changed=copy.deepcopy(self.listing);changed['listings'][0]['price']=600000
        result=self.save(changed,revision=4)
        self.assertEqual(result['moderation']['boarding']['status'],'pending')
        self.assertEqual(self.public(),[])

    def test_owner_pause_can_resume_but_admin_suspension_cannot_be_bypassed(self):
        self.save();self.review()
        paused=copy.deepcopy(self.listing);paused['listings'][0]['active']=False
        self.save(paused,2)
        self.assertEqual(self.public(),[])
        self.save(revision=3)
        self.assertEqual(len(self.public()),1)
        self.review(4,'suspend')
        self.save(revision=5)
        self.assertEqual(self.public(),[])
        self.review(6)
        self.save({'housing':'house','listings':[]},7)
        self.assertEqual(self.public(),[])
        with server.db() as con:
            self.assertIn('abc:boarding',catalog.known_names(con))

    def test_no_implicit_identity_approval_or_incomplete_profile(self):
        self.save()
        for environment,test in [('production',True),('local',False)]:
            with self.assertRaises(catalog.CatalogError): self.review(environment=environment,test=test)
        incomplete=copy.deepcopy(self.account);incomplete['profile']['photo']=None
        with server.db() as con: con.execute("UPDATE users SET account=? WHERE id='abc'",(json.dumps(incomplete),))
        with self.assertRaisesRegex(catalog.CatalogError,'profil rasmi'):
            self.review()
        with server.db() as con:
            self.assertEqual(catalog.document(con,'abc')['_revision'],1)

    def test_profile_change_invalidates_pending_admin_form_revision(self):
        self.save()
        changed=copy.deepcopy(self.account);changed['sitterProfile']['about']='Changed terms'
        with server.db() as con:
            catalog.invalidate_profile(con,'abc',self.account,changed)
            con.execute("UPDATE users SET account=? WHERE id='abc'",(json.dumps(changed),))
        with self.assertRaises(catalog.CatalogError): self.review()

    def test_archive_keeps_editable_terms_and_restoration_requires_review(self):
        self.save();self.review()
        with server.db() as con:
            saved=catalog.archive(con,'abc','boarding',2)
        self.assertEqual(saved['moderation']['boarding']['status'],'archived')
        self.assertEqual(saved['listings'][0]['price'],500000)
        self.assertFalse(saved['listings'][0]['active'])
        self.assertEqual(self.public(),[])
        self.save(revision=3)
        self.assertEqual(self.public(),[])
        self.review(4)
        self.assertEqual(len(self.public()),1)
