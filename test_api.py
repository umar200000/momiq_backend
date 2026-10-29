import base64
import http.cookiejar
import json
import os
import sqlite3
from pathlib import Path
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from urllib.request import Request, build_opener, HTTPCookieProcessor
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
import server
from test_media import fixture_image

class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        server.DATA = Path(cls.temp.name)
        os.environ['MOMIQ_ADMIN_PASSWORD'] = 'test-admin-password'
        server.setup()
        with server.db() as con:
            con.execute("INSERT INTO sitters(id,profile) VALUES(?,?)", ("hoji", json.dumps({"name":"Test sitter"})))
        cls.http = ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.base = 'http://127.0.0.1:'+str(cls.http.server_port)
        cls.thread = threading.Thread(target=cls.http.serve_forever,daemon=True)
        cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join()
        cls.temp.cleanup()
    def setUp(self):
        with server.db() as con: con.execute('DELETE FROM attempts')
        self.client = build_opener()
        self.admin = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.req('/api/admin/login','POST',{'username':'admin','password':'test-admin-password'},admin=True)
    def req(self,path,method='GET',data=None,token=None,admin=False,expected=200,origin=None):
        headers={}
        if data is not None: headers['Content-Type']='application/json'
        if token: headers['Authorization']='Bearer '+token
        if origin: headers['Origin']=origin
        request=Request(self.base+path,data=json.dumps(data).encode() if data is not None else None,headers=headers,method=method)
        try: response=(self.admin if admin else self.client).open(request)
        except HTTPError as e: response=e
        with response:
            self.assertEqual(response.status,expected)
            return json.loads(response.read())
    def login(self,phone='998901111111'):
        return self.req('/api/auth/login','POST',{'phone':phone,'code':'111111'})
    def test_notifications_are_owner_scoped_paginated_and_read_idempotently(self):
        import notifications
        a=self.login('998900000011');b=self.login('998900000012')
        with server.db() as con:
            con.execute('BEGIN IMMEDIATE')
            for i in range(23):
                notifications.publish(con,a['userId'],'test-notice:'+str(i),'wallet_topup',str(i),'approved','TEST only')
        first=self.req('/api/notifications',token=a['token'])
        self.assertEqual(len(first['items']),20);self.assertEqual(first['unreadCount'],23)
        second=self.req('/api/notifications?before='+first['nextCursor'],token=a['token'])
        self.assertEqual(len(second['items']),3);self.assertIsNone(second['nextCursor'])
        self.assertFalse(set(x['id'] for x in first['items']) & set(x['id'] for x in second['items']))
        self.assertEqual(self.req('/api/notifications',token=b['token'])['items'],[])
        path='/api/notifications/'+first['items'][0]['id']+'/read'
        self.req(path,'POST',{},token=b['token'],expected=404)
        self.req(path,'POST',{},token=a['token']);self.req(path,'POST',{},token=a['token'])
        self.assertEqual(self.req('/api/notifications',token=a['token'])['unreadCount'],22)
        self.req('/api/notifications?before=-1',token=a['token'],expected=400)
        self.req('/api/notifications',expected=401)

    def test_roles_and_server_listings(self):
        login = self.req('/api/auth/login','POST',{'phone':'998909991122','code':'111111','role':'sitter'})
        token, uid = login['token'],login['userId']
        users = self.req('/api/admin/users?q='+uid,admin=True)['users']
        self.assertEqual(next(u for u in users if u['id']==uid)['roles'],['sitter'])
        payload = {'housing':'house','listings':[{'type':'boarding','pets':['cat'],'price':100000,'capacity':2,'location':{'lat':41.3,'lon':69.2,'address':'Test address'},'active':True}]}
        self.req('/api/me/listings','PUT',payload,token=token,expected=403)
        account=login['account'];account['profile'].update(first='Sitter',last='Test')
        account['sitterProfile']={'years':1,'about':'','homePhotos':[],'housing':'house'}
        self.req('/api/me','PUT',account,token=token)
        self.req('/api/me/listings','PUT',payload,token=token,expected=428)
        payload['_revision']=0
        saved=self.req('/api/me/listings','PUT',payload,token=token)
        self.assertEqual(saved['listings'],payload['listings'])
        self.assertEqual(saved['moderation']['boarding']['status'],'pending')
        self.req('/api/me/listings','PUT',payload,token=token,expected=409)
        self.assertEqual(self.req('/api/me/listings',token=token),saved)
        other=self.login('998909991133')
        self.assertEqual(self.req('/api/me/listings',token=other['token'])['listings'],[])
        self.req('/api/admin/listings',token=token,expected=401)
        ads=self.req('/api/admin/listings',admin=True)['listings']
        self.assertEqual(next(a for a in ads if a['userId']==uid)['price'],100000)
        review_path='/api/admin/listings/'+uid+'/boarding/review'
        review={'decision':'approve','reason':'TEST review','testOnly':True,'_revision':1}
        self.req(review_path,'POST',review,token=token,expected=401)
        self.req(review_path,'POST',review,admin=True,expected=409) # incomplete profile
        bad=json.loads(json.dumps(payload));bad['housing']='apartment'
        self.req('/api/me/listings','PUT',bad,token=token,expected=400)
        bad=json.loads(json.dumps(payload));bad['listings'][0]['price']=True
        self.req('/api/me/listings','PUT',bad,token=token,expected=400)
        bad=json.loads(json.dumps(payload));bad['listings'].append(dict(bad['listings'][0],type='personal',capacity=None))
        self.req('/api/me/listings','PUT',bad,token=token,expected=400)
        self.assertEqual(self.req('/api/me/listings',token=token),saved)
        self.req('/api/auth/logout','POST',{},token=token)
        again=self.req('/api/auth/login','POST',{'phone':'998909991122','code':'111111','role':'customer'})
        self.assertEqual(self.req('/api/me/listings',token=again['token']),saved)
        archived=self.req('/api/me/listings/boarding/archive','POST',{'_revision':saved['_revision']},token=again['token'])
        self.assertEqual(archived['moderation']['boarding']['status'],'archived')
        self.assertFalse(archived['listings'][0]['active'])
        self.assertEqual(archived['listings'][0]['price'],100000)
        self.req('/api/me/listings/boarding/archive','POST',{'_revision':saved['_revision']},token=again['token'],expected=409)
        users=self.req('/api/admin/users?q='+uid,admin=True)['users']
        self.assertEqual(next(u for u in users if u['id']==uid)['roles'],['customer','sitter'])
        server.setup()
        with server.db() as con:
            self.assertEqual(server.roles_for(con,uid),['customer','sitter'])

    def test_role_enrollment_preserves_account_and_grants_no_approval_or_admin_rights(self):
        login=self.login('998909991144');uid=login['userId'];token=login['token']
        before=self.req('/api/me',token=token)
        role=self.req('/api/me/role','POST',{'role':'sitter'},token=token)
        self.assertEqual(role['roles'],['customer','sitter'])
        self.assertEqual(role['account'],before['account'])
        self.assertEqual(role['userId'],uid)
        self.assertEqual(self.req('/api/me/role','POST',{'role':'sitter'},token=token),role)
        self.assertEqual(self.req('/api/me/role','POST',{'role':'customer'},token=token)['role'],'customer')
        for data in [{'role':'admin'}, {'role':'sitter','userId':'someone'}, {'role':None}]:
            self.req('/api/me/role','POST',data,token=token,expected=400)
        self.req('/api/me/role','GET',token=token,expected=405)
        self.req('/api/me/role','POST',{'role':'sitter'},expected=401)
        self.req('/api/admin/users',token=token,expected=401)
        payload={'housing':'house','listings':[],'_revision':0}
        self.req('/api/me/listings','PUT',payload,token=token,expected=403)
        self.assertEqual(self.req('/api/me',token=token),before)
        with server.db() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM audit WHERE actor=? AND action='role-enroll'",(uid,)).fetchone()[0],1)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM listing_moderation WHERE user_id=?',(uid,)).fetchone()[0],0)
            con.execute('UPDATE users SET blocked=1 WHERE id=?',(uid,))
        self.req('/api/me/role','POST',{'role':'sitter'},token=token,expected=403)

    def test_catalog_contains_only_database_records(self):
        # Legacy, unreviewed demo records are references, never public ads.
        self.assertEqual(self.req('/api/sitters')['sitters'], [])
        with server.db() as con:
            con.execute("UPDATE sitters SET active=0 WHERE id='hoji'")
        try:
            self.assertEqual(self.req('/api/sitters')['sitters'], [])
            self.assertEqual(self.req('/api/admin/users',admin=True)['sitters']['hoji'],'Test sitter')
        finally:
            with server.db() as con:
                con.execute("UPDATE sitters SET active=1 WHERE id='hoji'")

    def test_registered_profile_survives_logout_and_new_login(self):
        first = self.login('998908888888')
        self.assertEqual(first['account']['profile']['first'], '')
        account = first['account']
        account['profile'].update(first='Actual', last='Person')
        account['sitterProfile'] = {'years':2,'about':'Pet care','homePhotos':[],'housing':'house'}
        self.req('/api/me','PUT',account,token=first['token'])
        self.req('/api/auth/logout','POST',{},token=first['token'])
        self.req('/api/me',token=first['token'],expected=401)
        second = self.login('998908888888')
        self.assertEqual(first['userId'],second['userId'])
        self.assertEqual(second['account']['profile']['first'],'Actual')
        self.assertEqual(second['account']['sitterProfile']['years'],2)

    def test_auth_and_account_isolation(self):
        a=self.login();b=self.login('998902222222')
        self.req('/api/me',expected=401)
        self.req('/api/admin/users',token=a['token'],expected=401)
        account=a['account'];account['profile'].update(first='Umar',last='Test')
        self.req('/api/me','PUT',account,token=a['token'])
        self.assertEqual(self.req('/api/me',token=a['token'])['account']['profile']['first'],'Umar')
        self.assertEqual(self.req('/api/me',token=b['token'])['account']['profile']['first'],'')

    def test_stale_profile_and_admin_updates_do_not_overwrite(self):
        a = self.login('998909000001')
        original = a['account']
        original['profile'].update(first='Initial',last='Name')
        current = self.req('/api/me','PUT',original,token=a['token'])['account']
        stale = json.loads(json.dumps(current))
        current['language'] = 'ru'
        saved = self.req('/api/me','PUT',current,token=a['token'])['account']
        stale['profile']['first'] = 'Lost change'
        self.req('/api/me','PUT',stale,token=a['token'],expected=409)
        self.req('/api/admin/users/'+a['userId'],'PUT',{'account':stale,'_revision':stale['_revision'],'reason':'TEST conflict check'},admin=True,expected=409)
        self.assertEqual(self.req('/api/me',token=a['token'])['account'],saved)
        missing = dict(saved); missing.pop('_revision')
        self.req('/api/me','PUT',missing,token=a['token'],expected=428)
        self.req('/api/me','PUT',dict(saved,_revision=True),token=a['token'],expected=400)
        self.assertEqual(self.req('/api/me',token=a['token'])['account'],saved)

    def test_parallel_profile_updates_have_one_winner(self):
        from concurrent.futures import ThreadPoolExecutor
        a=self.login('998909000002')
        a['account']['profile'].update(first='Before',last='Test')
        start=self.req('/api/me','PUT',a['account'],token=a['token'])['account']
        barrier=threading.Barrier(2)
        def update(language):
            payload=dict(start,language=language)
            request=Request(self.base+'/api/me',data=json.dumps(payload).encode(),method='PUT',headers={'Content-Type':'application/json','Authorization':'Bearer '+a['token']})
            barrier.wait()
            try: response=build_opener().open(request)
            except HTTPError as e: response=e
            with response: return response.status
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(update,['ru','en']))
        self.assertEqual(sorted(outcomes),[200,409])
        saved=self.req('/api/me',token=a['token'])['account']
        self.assertEqual(saved['_revision'],start['_revision']+1)

    def test_session_expiry_and_all_device_revocation(self):
        import time
        a=self.login('998909000003'); b=self.login('998909000003')
        other=self.login('998909000004')
        self.req('/api/auth/logout','POST',{},token=a['token'])
        self.req('/api/me',token=a['token'],expected=401)
        self.req('/api/me',token=b['token'])
        c=self.login('998909000003')
        self.req('/api/auth/logout-all','POST',{},token=b['token'])
        self.req('/api/me',token=b['token'],expected=401)
        self.req('/api/me',token=c['token'],expected=401)
        self.req('/api/me',token=other['token'])
        with server.db() as con:
            con.execute('UPDATE sessions SET expires=? WHERE user_id=?', (time.time()-1,other['userId']))
        self.req('/api/me',token=other['token'],expected=401)

    def test_profile_shapes_defaults_and_sitter_preferences(self):
        a=self.login('998909000005')
        account=a['account']; account['profile'].update(first='Sitter',last='Preferences')
        for key,value in [('profile',[]),('notifications',[]),('notifications',None),('support',[None])]:
            with self.subTest(key=key,value=value):
                self.req('/api/me','PUT',dict(account,**{key:value}),token=a['token'],expected=400)
        png=fixture_image()
        pet={'id':'minimal','type':'Mushuk','photo':png,'notes':None}
        account['pets']=[pet]
        account['addresses']=[{'id':'home','label':None,'address':'Toshkent','lat':41.3,'lon':69.2}]
        account['sitterProfile']={'years':1,'about':'Care','homePhotos':[],'housing':'house','schedule':{'days':[True]*5+[False]*2,'start':540,'end':1080}}
        saved=self.req('/api/me','PUT',account,token=a['token'])['account']
        self.assertEqual(saved['pets'][0]['notes'],'')
        self.assertEqual(saved['pets'][0]['age'],'')
        self.assertEqual(saved['addresses'][0]['apartment'],'')
        self.assertEqual(saved['sitterProfile']['schedule']['timezone'],'Asia/Tashkent')
        for bad_pet in [dict(pet,age=False),dict(pet,age='101'),dict(pet,id=''),dict(pet,sex='invalid')]:
            self.req('/api/me','PUT',dict(saved,pets=[bad_pet]),token=a['token'],expected=400)
        self.req('/api/me','PUT',dict(saved,pets=[pet,pet]),token=a['token'],expected=400)
        invalid=json.loads(json.dumps(saved)); invalid['addresses'][0]['lat']=True
        self.req('/api/me','PUT',invalid,token=a['token'],expected=400)
        for schedule in [None,{'days':[True]*6,'start':0,'end':1},{'days':[True]*7,'start':1200,'end':500},{'days':[True]*7,'start':0,'end':1440}]:
            if schedule is None: continue
            invalid=json.loads(json.dumps(saved)); invalid['sitterProfile']['schedule']=schedule
            self.req('/api/me','PUT',invalid,token=a['token'],expected=400)
        saved['notifications']['video']=False; saved['language']='ru'
        updated=self.req('/api/me','PUT',saved,token=a['token'])['account']
        other=self.login('998909000005')
        self.assertEqual(other['account'],updated)

    def test_account_contract_rejects_malformed_nested_values_without_mutation(self):
        a=self.login('998909080001')
        payload=dict(a['account'],profile={'first':' Test ','last':' Owner ','photo':None})
        saved=self.req('/api/me','PUT',payload,token=a['token'])['account']
        malformed=[('favorites',[{}]),('favorites',[[]]),('favorites',[None]),
                   ('support',[{}]),('support',[{'id':'x'}]),('support',[{'text':'x'}]),
                   ('support',[{'id':'','text':'x'}]),('support',[{'id':'x','text':' '}]),
                   ('support',[{'id':'x','text':'a'},{'id':' x ','text':'b'}]),
                   ('profile',{'first':'x'*101,'last':'Owner'}),
                   ('profile',{'first':None,'last':'Owner'})]
        for key,value in malformed:
            with self.subTest(key=key,value=value):
                invalid=dict(saved,**{key:value})
                self.req('/api/me','PUT',invalid,token=a['token'],expected=400)
                self.req('/api/admin/users/'+a['userId'],'PUT',
                         {'account':invalid,'_revision':saved['_revision'],'reason':'TEST invalid data'},admin=True,expected=400)
                self.assertEqual(self.req('/api/me',token=a['token'])['account'],saved)
        for invalid in [[],{'housing':'house','listings':[[]]}]:
            self.req('/api/me/listings','PUT',invalid,token=a['token'],expected=400)

    def test_account_contract_normalized_values_survive_roundtrip(self):
        a=self.login('998909080002')
        png=fixture_image()
        payload={'_revision':a['account']['_revision'],
                 'profile':{'first':'  O‘zbek 😀  ','last':' Яна ','photo':None},
                 'favorites':['hoji','hoji'],
                 'pets':[{'id':' cat ','type':'Mushuk','photo':png,'name':None,'allergies':' TEST '}],
                 'addresses':[{'id':' home ','address':' Toshkent ','lat':41.3,'lon':69.2}],
                 'support':[{'id':' legacy ','text':' Archive ','untrustedStatus':'approved'}],
                 'sitterProfile':{'years':None,'about':''}}
        saved=self.req('/api/me','PUT',payload,token=a['token'])['account']
        self.assertEqual(saved['profile'],{'first':'O‘zbek 😀','last':'Яна','photo':None})
        self.assertEqual(saved['favorites'],['hoji'])
        self.assertEqual(saved['notifications'],{'orders':True,'chat':True,'video':True})
        self.assertEqual(saved['language'],'uz')
        self.assertEqual(saved['support'],[{'id':'legacy','text':'Archive'}])
        self.assertEqual(saved['sitterProfile'],{'years':None,'about':'','homePhotos':[],'housing':'apartment'})
        self.assertEqual(saved['pets'][0]['id'],'cat')
        self.assertEqual(saved['pets'][0]['allergies'],'TEST')
        self.assertEqual(saved['addresses'][0]['label'],'')
        self.assertEqual(self.req('/api/me',token=a['token'])['account'],saved)
        self.assertEqual(self.login('998909080002')['account'],saved)
        # Trimmed IDs still retain newer care fields omitted by an old writer.
        saved['pets'][0]['id']=' cat '
        del saved['pets'][0]['allergies']
        updated=self.req('/api/me','PUT',saved,token=a['token'])['account']
        self.assertEqual(updated['pets'][0]['allergies'],'TEST')

    def test_platform_settings_history_is_private_paginated_and_immutable(self):
        login=self.login('998900000051')
        path='/api/admin/platform-settings/history'
        self.req(path,expected=401)
        self.req(path,token=login['token'],expected=401)
        config=self.req('/api/admin/platform-settings',admin=True)
        for rate in [-1,10001,True,10.5,'1000']:
            self.req('/api/admin/platform-settings','PUT',dict(version=config['version'],commissionBps=rate,reason='TEST'),admin=True,expected=400)
        self.req('/api/admin/platform-settings','PUT',dict(version=config['version'],commissionBps=1000,reason=''),admin=True,expected=400)
        original=config['commissionBps']
        for rate in [0,10000,1234,original]:
            config=self.req('/api/admin/platform-settings','PUT',dict(version=config['version'],commissionBps=rate,reason='TEST rate boundary'),admin=True)
            self.assertEqual(config['commissionBps'],rate)
        with server.db() as con:
            for i in range(23):
                con.execute("INSERT INTO platform_settings(commission_bps,qr_image,test_only,actor,reason,created) VALUES(?,NULL,1,'admin',?,?)",(original,'TEST history '+str(i),server.now()))
        first=self.req(path,admin=True)
        self.assertEqual(len(first['items']),20)
        self.assertTrue(first['nextCursor'])
        self.assertNotIn('qrImage',str(first)); self.assertNotIn('receipt',str(first))
        self.assertEqual(first['items'][0]['actor'],'admin')
        self.assertTrue(first['items'][0]['effectiveAt'].endswith('+00:00'))
        # New settings during pagination do not repeat or displace older entries.
        with server.db() as con:
            con.execute("INSERT INTO platform_settings(commission_bps,qr_image,test_only,actor,reason,created) VALUES(?,NULL,1,'admin','TEST newer',?)",(original,server.now()))
        second=self.req(path+'?before='+first['nextCursor'],admin=True)
        self.assertTrue(second['items'])
        self.assertFalse(set(i['version'] for i in first['items']) & set(i['version'] for i in second['items']))
        self.assertTrue(all(i['version']<int(first['nextCursor']) for i in second['items']))
        for query in ['?before=','?before=-1','?before=0','?before=1&before=2','?unknown=1','?before=1%20OR%201=1']:
            self.req(path+query,admin=True,expected=400)
        for statement in ['UPDATE platform_settings SET commission_bps=1','DELETE FROM platform_settings']:
            with self.assertRaises(sqlite3.IntegrityError):
                with server.db() as con: con.execute(statement)

    def test_pet_safety_validation_legacy_roundtrip_and_owner_scope(self):
        a=self.login('998900000041');other=self.login('998900000042')
        a['account']['profile'].update(first='TEST',last='Care')
        values={'vaccinations':'TEST passport notes', 'allergies':'TEST fish',
                'medications':'TEST owner instruction', 'behavior':'TEST timid',
                'emergencyName':'TEST contact', 'emergencyPhone':'+998900000099'}
        pet=dict(id='safety-pet',type='Mushuk',photo=fixture_image(),**values)
        saved=self.req('/api/me','PUT',dict(a['account'],pets=[pet]),token=a['token'])['account']
        for field,value in values.items(): self.assertEqual(saved['pets'][0][field],value)
        # Old mobile versions omit new fields; omission must not erase care facts.
        legacy=json.loads(json.dumps(saved))
        for field in values: legacy['pets'][0].pop(field)
        saved=self.req('/api/me','PUT',legacy,token=a['token'])['account']
        for field,value in values.items(): self.assertEqual(saved['pets'][0][field],value)
        self.assertEqual(self.req('/api/me',token=other['token'])['account']['pets'],[])
        for field,value in [('allergies',False),('medications','x'*2001),('emergencyName','x'*121),
                            ('emergencyPhone','99890'),('emergencyPhone','+998 90'),('behavior','x\x00')]:
            invalid=json.loads(json.dumps(saved));invalid['pets'][0][field]=value
            self.req('/api/me','PUT',invalid,token=a['token'],expected=400)
        # Explicit clear is supported and unknown never becomes a medical claim.
        saved['pets'][0].update({field:None for field in values})
        cleared=self.req('/api/me','PUT',saved,token=a['token'])['account']
        for field in values: self.assertEqual(cleared['pets'][0][field],'')
        self.assertFalse(any(cleared['pets'][0].get(k) for k in ['vaccinated','healthy']))

    def test_pet_archive_restore_ownership_revision_and_legacy_saves(self):
        login=self.login('998909000021'); token=login['token']
        other=self.login('998909000022')
        account=login['account']; account['profile'].update(first='TEST',last='Pet')
        account['pets']=[{'id':'owned-pet','type':'Mushuk','photo':fixture_image(),'name':'TEST cat'}]
        saved=self.req('/api/me','PUT',account,token=token)['account']
        body={'petId':'owned-pet','archived':True,'_revision':saved['_revision']}
        self.req('/api/me/pets/archive','POST',dict(body,_revision=other['account']['_revision']),token=other['token'],expected=404)
        self.req('/api/me/pets/archive','POST',dict(body,archived=1),token=token,expected=400)
        self.req('/api/me/pets/archive','POST',{'petId':'owned-pet','archived':True},token=token,expected=428)
        archived=self.req('/api/me/pets/archive','POST',body,token=token)['account']
        self.assertTrue(archived['pets'][0]['archived'])
        self.assertEqual(self.req('/api/me/pets/archive','POST',body,token=token)['account'],archived)
        self.req('/api/me/pets/archive','POST',dict(body,archived=False),token=token,expected=409)
        # Old clients must not drop an archived animal by serializing active only.
        legacy=dict(archived,pets=[])
        retained=self.req('/api/me','PUT',legacy,token=token)['account']
        self.assertTrue(retained['pets'][0]['archived'])
        retained['pets'][0].pop('archived')
        retained=self.req('/api/me','PUT',retained,token=token)['account']
        self.assertTrue(retained['pets'][0]['archived'])
        restored=self.req('/api/me/pets/archive','POST',dict(body,archived=False,_revision=retained['_revision']),token=token)['account']
        self.assertFalse(restored['pets'][0]['archived'])
        self.assertEqual(restored['pets'][0]['name'],'TEST cat')
        self.assertEqual(self.login('998909000021')['account'],restored)

    def test_ambiguous_json_login_rejected_over_http(self):
        for raw in (b'{"username":"intruder","username":"admin","password":"test-admin-password"}',
                    b'{"username":"admin","password":"test-admin-password","extra":NaN}',
                    b'{"username":"admin","password":"test-admin-password","extra":'+b'['*64+b'0'+b']'*64+b'}'):
            request=Request(self.base+'/api/admin/login',data=raw,headers={'Content-Type':'application/json'},method='POST')
            with self.assertRaises(HTTPError) as caught:self.client.open(request)
            with caught.exception as response:
                self.assertEqual(response.status,400)
                self.assertNotIn('Set-Cookie',response.headers)
                self.assertNotIn(b'test-admin-password',response.read())

    def test_topup_corrections_admin_only_owner_history_and_pagination(self):
        import wallet
        a=self.req('/api/auth/login','POST',{'phone':'998909008065','code':'111111','role':'sitter'})
        b=self.req('/api/auth/login','POST',{'phone':'998909008066','code':'111111','role':'sitter'})
        tid='65000000000000000000000000000001'
        with server.db() as con:
            con.execute('BEGIN IMMEDIATE')
            con.execute("INSERT INTO topup_requests(id,user_id,amount_minor,receipt,receipt_hash,qr_version,terms_version,request_id,status,created,transfer_reference) VALUES(?,?,10000,'TEST','test-correction-http',1,'v1','fixture','approved',?,'TEST-CORRECTION-HTTP')",(tid,a['userId'],server.now()))
            wallet.post_entry(con,a['userId'],10000,'topup','topup:'+tid,'fixture-admin','TEST synthetic credit')
        path='/api/admin/topups/'+tid+'/corrections'
        body={'requestId':'correction-http','amountMinor':100,'expectedCorrectedMinor':0,'reason':'TEST over-credit'}
        self.req(path,token=a['token'],expected=401)
        self.req(path,'POST',body,token=a['token'],expected=401)
        self.req('/api/wallet/topups/'+tid+'/corrections','POST',body,token=a['token'],expected=405)
        result=self.req(path,'POST',body,admin=True)['correction']
        self.assertEqual(self.req(path,'POST',body,admin=True)['correction'],result)
        self.assertEqual(result['actor'],'admin')
        for i in range(1,22):
            self.req(path,'POST',dict(body,requestId='correction-http-'+str(i),expectedCorrectedMinor=i*100),admin=True)
        private='/api/wallet/topups/'+tid+'/corrections'
        self.req(private,token=b['token'],expected=404)
        page=self.req(private,token=a['token'])
        self.assertEqual(len(page['items']),20)
        self.assertEqual(page['correctedMinor'],2200)
        self.assertEqual(page['balanceMinor'],7800)
        self.assertNotIn('actor',page['items'][0]);self.assertIsNone(page['transferReference'])
        older=self.req(private+'?before='+page['nextCursor'],token=a['token'])
        self.assertEqual(len(older['items']),2);self.assertIsNone(older['nextCursor'])
        self.assertEqual(len({v['id'] for v in page['items']+older['items']}),22)
        self.req(private+'?before='+('f'*32),token=a['token'],expected=400)
        self.req(private+'?unknown=1',token=a['token'],expected=400)
        admin=self.req(path,admin=True)
        self.assertEqual(admin['transferReference'],'TEST-CORRECTION-HTTP')
        ledger=self.req('/api/wallet',token=a['token'])
        self.assertEqual(ledger['balanceMinor'],7800)
        corrections=[entry for entry in ledger['entries'] if entry['kind']=='topup_correction']
        self.assertEqual(len(corrections),22)
        self.assertTrue(all(entry['topupId']==tid for entry in corrections))

    def test_manual_topup_verification_idempotency_and_access(self):
        from concurrent.futures import ThreadPoolExecutor
        a=self.req('/api/auth/login','POST',{'phone':'998909000006','code':'111111','role':'sitter'})
        b=self.login('998909000007')
        self.req('/api/wallet',token=b['token'],expected=403)
        self.req('/api/admin/topups',token=a['token'],expected=401)
        config=self.req('/api/admin/platform-settings',admin=True)
        self.assertEqual(config['commissionBps'],1000)
        png=fixture_image('green')
        config=self.req('/api/admin/platform-settings','PUT',{'version':config['version'],'qrImage':png,'testOnly':True,'reason':'TEST only QR','recipientName':'TEST recipient','qrActive':True},admin=True)
        payload={'payerReference':'TEST-PAYER-001','paidAt':'2026-10-26T10:00:00+05:00','requestId':'once','amountMinor':2_000_000,'receipt':png,'qrVersion':config['version'],'termsVersion':'balance-no-refund-v1','acceptNonRefundable':True}
        self.req('/api/wallet/topups','POST',dict(payload,acceptNonRefundable=False),token=a['token'],expected=400)
        self.req('/api/wallet/topups','POST',dict(payload,payerReference='',paidAt=None),token=a['token'],expected=400)
        self.req('/api/wallet/topups','POST',dict(payload,paidAt='2099-01-01T00:00:00Z'),token=a['token'],expected=400)
        created=self.req('/api/wallet/topups','POST',payload,token=a['token'],expected=201)['topup']
        self.assertEqual(created['payerReference'],'TEST-PAYER-001')
        self.assertEqual(created['paidAt'],'2026-10-26T05:00:00+00:00')
        self.req('/api/wallet/topups','POST',dict(payload,payerReference='changed'),token=a['token'],expected=409)
        receipt_path='/api/wallet/topups/'+created['id']+'/receipt'
        self.assertEqual(self.req(receipt_path,token=a['token'])['receipt'],png)
        other=self.req('/api/auth/login','POST',{'phone':'998909000008','code':'111111','role':'sitter'})
        self.req(receipt_path,token=other['token'],expected=404)
        self.req('/api/admin/topups/'+created['id']+'/receipt',token=a['token'],expected=401)
        self.assertEqual(self.req('/api/admin/topups/'+created['id']+'/receipt',admin=True)['receipt'],png)
        changed=self.req('/api/admin/platform-settings','PUT',{'version':config['version'],'qrActive':False,'recipientName':'NEW recipient','reason':'Pause new payments'},admin=True)
        self.assertFalse(changed['qrActive'])
        snapshot=self.req('/api/admin/topups/'+created['id']+'/receipt',admin=True)['paymentSnapshot']
        self.assertEqual(snapshot['recipientName'],'TEST recipient')
        self.assertEqual(snapshot['qrImage'],png)
        self.req('/api/wallet/topups','POST',dict(payload,requestId='paused',receipt=fixture_image('yellow'),qrVersion=changed['version']),token=a['token'],expected=409)
        # Already paid on a prior active version: evidence remains submittable.
        late=self.req('/api/wallet/topups','POST',dict(payload,requestId='previous-version',receipt=fixture_image('purple')),token=a['token'],expected=201)['topup']
        self.req('/api/admin/topups/'+late['id']+'/review','POST',{'revision':0,'decision':'reject','reason':'TEST only prior-version evidence'},admin=True)
        self.req('/api/admin/platform-settings','PUT',{'version':changed['version'],'qrActive':True,'recipientName':'','reason':'Invalid activation'},admin=True,expected=400)
        self.assertNotIn('receipt',self.req('/api/admin/topups?status=pending',admin=True)['topups'][0])
        admin_topup=next(item for item in self.req('/api/admin/topups?status=pending',admin=True)['topups'] if item['id']==created['id'])
        self.assertEqual(admin_topup['owner']['phone'],'998909000006')
        self.assertEqual(set(admin_topup['owner']),{'name','phone'})
        self.assertNotIn('owner',self.req('/api/wallet/topups',token=a['token'])['topups'][0])
        self.req('/api/wallet/topups?cursor='+created['id'],token=other['token'],expected=400)
        self.req('/api/admin/platform-settings','PUT',{'version':config['version']-1,'reason':'stale'},admin=True,expected=409)
        self.assertEqual(self.req('/api/wallet',token=a['token'])['balanceMinor'],0)
        self.assertEqual(self.req('/api/wallet/topups','POST',payload,token=a['token'])['topup']['id'],created['id'])
        self.req('/api/wallet/topups','POST',dict(payload,amountMinor=3_000_000),token=a['token'],expected=409)
        self.req('/api/wallet/topups','POST',dict(payload,requestId='duplicate'),token=a['token'],expected=409)
        path='/api/admin/topups/'+created['id']+'/review'
        decision={'revision':0,'decision':'approve','fundsVerified':True,'receivedAmountMinor':2_000_000,'transferReference':'TEST-XOLIS-1','reason':'TEST receipt and incoming funds verified'}
        self.req(path,'POST',dict(decision,fundsVerified=False),admin=True,expected=400)
        self.req(path,'POST',dict(decision,receivedAmountMinor=1_000_000),admin=True,expected=409)
        # Two independently authenticated operators race to approve the same receipt.
        operator=build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        login=Request(self.base+'/api/admin/login',method='POST',headers={'Content-Type':'application/json'},data=json.dumps({'username':'admin','password':'test-admin-password'}).encode())
        with operator.open(login) as response: response.read()
        barrier=threading.Barrier(2)
        def approve(opener):
            request=Request(self.base+path,method='POST',headers={'Content-Type':'application/json'},data=json.dumps(decision).encode())
            barrier.wait()
            with opener.open(request) as response: return response.status
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(approve,[self.admin,operator])),[200,200])
        result=self.req('/api/wallet',token=a['token'])
        self.assertEqual(result['balanceMinor'],2_000_000)
        self.assertEqual(len(result['entries']),1)
        notices=self.req('/api/notifications',token=a['token'])['items']
        self.assertEqual(len([n for n in notices if n['targetId']==created['id']]),1)
        self.assertEqual(next(n for n in notices if n['targetId']==created['id'])['status'],'approved')
        self.assertTrue(result['balanceEligible'])
        self.req(path,'POST',{'revision':0,'decision':'reject','reason':'Conflicting decision'},admin=True,expected=409)
        with server.db() as con:
            self.assertEqual(con.execute('SELECT SUM(amount_minor) FROM wallet_entries WHERE user_id=?',(a['userId'],)).fetchone()[0],result['balanceMinor'])
            with self.assertRaisesRegex(sqlite3.IntegrityError,'immutable'): con.execute('UPDATE wallet_entries SET amount_minor=1 WHERE user_id=?',(a['userId'],))
        # A different receipt cannot credit the same real incoming transfer twice.
        payload.update(requestId='second',receipt=fixture_image('blue'))
        second=self.req('/api/wallet/topups','POST',payload,token=a['token'],expected=201)['topup']
        self.req('/api/admin/topups/'+second['id']+'/review','POST',decision,admin=True,expected=409)
        self.assertEqual(self.req('/api/wallet',token=a['token'])['balanceMinor'],2_000_000)
        self.req('/api/admin/topups/'+second['id']+'/review','POST',{'revision':0,'decision':'reject','reason':'TEST duplicate incoming transfer'},admin=True)
        self.assertEqual(self.req('/api/wallet/topups',token=a['token'])['topups'][0]['status'],'rejected')
        self.assertEqual(self.req('/api/admin/topups?status=pending',admin=True)['topups'],[])

    def test_same_transfer_with_reencoded_receipts_cannot_credit_two_sitters(self):
        from concurrent.futures import ThreadPoolExecutor
        a=self.req('/api/auth/login','POST',{'phone':'998909000031','code':'111111','role':'sitter'})
        b=self.req('/api/auth/login','POST',{'phone':'998909000032','code':'111111','role':'sitter'})
        config=self.req('/api/admin/platform-settings',admin=True)
        config=self.req('/api/admin/platform-settings','PUT',dict(version=config['version'],qrImage=fixture_image('orange'),qrActive=True,recipientName='TEST ONLY',reason='TEST duplicate receipt'),admin=True)
        png=fixture_image('#123456');jpeg=fixture_image('#123456',format='JPEG')
        self.assertNotEqual(png,jpeg)
        payload={'requestId':'same-payment','amountMinor':100,'qrVersion':config['version'],
                 'termsVersion':'balance-no-refund-v1','acceptNonRefundable':True,'payerReference':'TEST shared evidence'}
        first=self.req('/api/wallet/topups','POST',dict(payload,receipt=png),token=a['token'],expected=201)['topup']
        # Exact image reuse is blocked across owners, before operator review.
        self.req('/api/wallet/topups','POST',dict(payload,receipt=png),token=b['token'],expected=409)
        second=self.req('/api/wallet/topups','POST',dict(payload,receipt=jpeg),token=b['token'],expected=201)['topup']
        operator=build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        login=Request(self.base+'/api/admin/login',method='POST',headers={'Content-Type':'application/json'},data=json.dumps({'username':'admin','password':'test-admin-password'}).encode())
        with operator.open(login) as response: self.assertEqual(response.status,200)
        barrier=threading.Barrier(2)
        def approve(args):
            opener,tid,reference=args
            body={'revision':0,'decision':'approve','fundsVerified':True,'receivedAmountMinor':100,
                  'transferReference':reference,'reason':'TEST independently checked incoming transfer'}
            request=Request(self.base+'/api/admin/topups/'+tid+'/review',method='POST',headers={'Content-Type':'application/json'},data=json.dumps(body).encode())
            barrier.wait(timeout=5)
            try: response=opener.open(request)
            except HTTPError as error: response=error
            with response: return response.status
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(approve,[(self.admin,first['id'],' TEST-ONE-INCOMING-TRANSFER '),
                                          (operator,second['id'],'test-one-incoming-transfer')]))
        self.assertEqual(sorted(results),[200,409])
        balances=[self.req('/api/wallet',token=owner['token'])['balanceMinor'] for owner in (a,b)]
        self.assertEqual(sorted(balances),[0,100])
        with server.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM wallet_entries WHERE user_id IN (?,?)',(a['userId'],b['userId'])).fetchone()[0],1)
            statuses=[r[0] for r in con.execute('SELECT status FROM topup_requests WHERE id IN (?,?)',(first['id'],second['id']))]
            self.assertEqual(sorted(statuses),['approved','pending'])

    def test_wallet_clarification_preserves_evidence_and_blocks_stale_credit(self):
        a=self.req('/api/auth/login','POST',{'phone':'998909000021','code':'111111','role':'sitter'})
        other=self.req('/api/auth/login','POST',{'phone':'998909000022','code':'111111','role':'sitter'})
        config=self.req('/api/admin/platform-settings',admin=True)
        config=self.req('/api/admin/platform-settings','PUT',dict(version=config['version'],qrImage=fixture_image('cyan'),qrActive=True,recipientName='TEST ONLY',reason='TEST clarification QR'),admin=True)
        original={'requestId':'clarification-original','amountMinor':100,'receipt':fixture_image('cyan'),'qrVersion':config['version'],'termsVersion':'balance-no-refund-v1','acceptNonRefundable':True,'payerReference':'TEST-CLARIFY-001'}
        topup=self.req('/api/wallet/topups','POST',original,token=a['token'],expected=201)['topup'];tid=topup['id']
        review='/api/admin/topups/'+tid+'/review'
        self.req(review,'POST',{'decision':'request_info','reason':'TEST: receipt amount unclear'},admin=True,expected=428)
        returned=self.req(review,'POST',{'revision':0,'decision':'request_info','reason':'TEST: receipt amount unclear'},admin=True)['topup']
        self.assertEqual((returned['status'],returned['revision']),('needs_info',1))
        edit=dict(original,requestId='edit-once',revision=1,amountMinor=200,receipt=fixture_image('pink'),payerReference='TEST-EDIT-001')
        amend='/api/wallet/topups/'+tid+'/amend'
        self.req(amend,'POST',edit,token=other['token'],expected=404)
        self.req(amend,'POST',dict(edit,revision=0),token=a['token'],expected=409)
        self.req(amend,'POST',dict(edit,qrVersion=config['version']+1),token=a['token'],expected=409)
        self.req(amend,'POST',dict(edit,acceptNonRefundable=False),token=a['token'],expected=400)
        changed=self.req(amend,'POST',edit,token=a['token'])['topup']
        self.assertEqual((changed['status'],changed['revision'],changed['amountMinor']),('pending',2,200))
        self.assertEqual(self.req('/api/wallet',token=a['token'])['balanceMinor'],0)
        approval={'revision':0,'decision':'approve','reason':'TEST verified','fundsVerified':True,'receivedAmountMinor':200,'transferReference':'TEST-CLARIFY-INCOMING-001'}
        self.req(review,'POST',approval,admin=True,expected=409)
        approval['revision']=2
        self.req(review,'POST',approval,admin=True);self.req(review,'POST',approval,admin=True)
        self.assertEqual(self.req('/api/wallet',token=a['token'])['balanceMinor'],200)
        self.assertEqual(self.req(amend,'POST',edit,token=a['token'])['topup']['status'],'approved')
        self.req(amend,'POST',dict(edit,amountMinor=300),token=a['token'],expected=409)
        self.assertEqual(self.req('/api/wallet/topups','POST',original,token=a['token'])['topup']['revision'],3)
        self.req('/api/wallet/topups','POST',dict(original,requestId='reuse-old-image'),token=a['token'],expected=409)
        history='/api/wallet/topups/'+tid+'/history'
        events=self.req(history,token=a['token'])['items']
        self.assertEqual([e['event'] for e in events],['approve','resubmitted','request_info','created'])
        self.assertTrue(all('receipt' not in e for e in events))
        self.assertEqual(self.req(history+'/0/receipt',token=a['token'])['receipt'],original['receipt'])
        self.assertEqual(self.req(history+'/2/receipt',token=a['token'])['receipt'],edit['receipt'])
        self.req(history,token=other['token'],expected=404)
        self.req(history+'/0/receipt',token=other['token'],expected=404)
        notices=self.req('/api/notifications',token=a['token'])['items']
        self.assertEqual([n['status'] for n in notices],['approved','needs_info'])
        with server.db() as con:
            with self.assertRaises(sqlite3.IntegrityError): con.execute('DELETE FROM topup_history WHERE topup_id=?',(tid,))

    def test_wallet_read_uses_one_snapshot_during_credit(self):
        from unittest.mock import patch
        import wallet
        a=self.req('/api/auth/login','POST',{'phone':'998909000009','code':'111111','role':'sitter'})
        with server.db() as con:
            con.execute('BEGIN IMMEDIATE')
            wallet.post_entry(con,a['userId'],100,'topup','snapshot-initial','test','synthetic')
        original_balance=wallet.balance
        injected=False
        def credit_between_reads(con,uid):
            nonlocal injected
            if not injected:
                injected=True
                with server.db() as writer:
                    writer.execute('BEGIN IMMEDIATE')
                    wallet.post_entry(writer,uid,200,'topup','snapshot-next','test','synthetic')
            return original_balance(con,uid)
        with patch.object(wallet,'balance',side_effect=credit_between_reads):
            result=self.req('/api/wallet',token=a['token'])
        self.assertEqual(result['balanceMinor'],100)
        self.assertEqual(sum(row['amountMinor'] for row in result['entries']),100)
        self.assertEqual(self.req('/api/wallet',token=a['token'])['balanceMinor'],300)

    def test_chat_reply_isolation_and_idempotency(self):
        a=self.login('998903333333');b=self.login('998904444444')
        message={'sitter':'hoji','text':'Salom','requestId':'once','senderRole':'support'}
        self.req('/api/messages','POST',message,token=a['token'],expected=409)
        # A historical conversation survives removal from discovery.
        with server.db() as con:
            con.execute('INSERT INTO messages(id,user_id,sitter,mine,text,time) VALUES(?,?,?,?,?,?)',('historical-chat',a['userId'],'hoji',0,'Old conversation','2020-01-01'))
        self.req('/api/messages','POST',message,token=a['token'])
        self.req('/api/messages','POST',message,token=a['token'])
        self.req('/api/messages','POST',dict(message,text='Changed retry'),token=a['token'],expected=409)
        self.req('/api/messages','POST',dict(message,image=fixture_image('pink')),token=a['token'],expected=409)
        self.assertEqual(len(self.req('/api/messages',token=a['token'])['messages']),2)
        self.assertEqual(self.req('/api/messages',token=b['token'])['messages'],[])
        data=self.req('/api/admin/users/'+a['userId']+'/messages','POST',{'sitter':'hoji','text':'Salom, javob','requestId':'reply'},admin=True)
        self.assertFalse(data['messages'][-1]['mine'])
        self.assertEqual(data['messages'][-1]['senderRole'],'support')
        self.assertEqual(data['messages'][-2]['senderRole'],'customer')
        self.req('/api/admin/users/'+a['userId']+'/messages','POST',{'sitter':'hoji','text':'Changed reply','requestId':'reply'},admin=True,expected=409)
        self.req('/api/admin/messages/'+data['messages'][-1]['id'],'DELETE',{'reason':'TEST remove reply'},admin=True)
        self.assertEqual(self.req('/api/messages',token=a['token'])['messages'][-1]['text'],'Xabar o‘chirildi')
    def test_admin_block_and_unblock(self):
        a=self.login('998905555555')
        self.req('/api/admin/users/'+a['userId'],'PUT',{'blocked':True,'_revision':a['account']['_revision'],'reason':'TEST restriction'},admin=True)
        self.req('/api/me',token=a['token'],expected=401)
        self.req('/api/auth/login','POST',{'phone':'998905555555','code':'111111'},expected=403)
        self.req('/api/admin/users/'+a['userId'],'PUT',{'blocked':False,'_revision':a['account']['_revision']+1,'reason':'TEST restored access'},admin=True)
        self.req('/api/me',token=a['token'],expected=401)
        fresh=self.login('998905555555')
        self.req('/api/me',token=fresh['token'])

    def test_admin_change_requires_reason_and_audits_bounded_before_after(self):
        a=self.login('998909880001');path='/api/admin/users/'+a['userId']
        original=self.req('/api/me',token=a['token'])['account']
        base={'blocked':False,'_revision':original['_revision']}
        for data in (base,{**base,'reason':''},{**base,'reason':True},{**base,'reason':'x'*1001},{**base,'reason':'TEST','actor':'forged'}):
            self.req(path,'PUT',data,admin=True,expected=400)
        self.assertEqual(self.req('/api/me',token=a['token'])['account'],original)
        account=json.loads(json.dumps(original));account['profile']={'first':'TEST corrected','last':'Owner','photo':fixture_image()}
        account['addresses']=[{'id':'test-home','label':'PRIVATE LABEL','address':'PRIVATE STREET 999','lat':41.3,'lon':69.2}]
        self.req(path,'PUT',{'account':account,'_revision':original['_revision'],'reason':' TEST operator correction '},admin=True)
        with server.db() as con:
            row=con.execute("SELECT actor,target FROM audit WHERE action='update-user' ORDER BY id DESC LIMIT 1").fetchone()
            self.assertEqual(row['actor'],'admin');detail=json.loads(row['target'])
            self.assertEqual(detail['userId'],a['userId']);self.assertEqual(detail['reason'],'TEST operator correction')
            self.assertEqual(detail['before']['revision'],original['_revision']);self.assertEqual(detail['after']['revision'],original['_revision']+1)
            self.assertEqual(detail['before']['profile']['first'],original['profile']['first'])
            self.assertEqual(detail['after']['profile']['first'],'TEST corrected')
            self.assertEqual(len(detail['after']['profile']['photoSha256']),64)
            self.assertNotEqual(detail['before']['accountSha256'],detail['after']['accountSha256'])
            self.assertEqual(detail['changedFields'],['addresses','profile'])
            for secret in (a['token'],account['profile']['photo'],'PRIVATE STREET 999','PRIVATE LABEL'):
                self.assertNotIn(secret,row['target'])

    def test_admin_audit_failure_rolls_back_profile_revision_block_and_sessions(self):
        a=self.login('998909880002');path='/api/admin/users/'+a['userId'];revision=a['account']['_revision']
        change={'blocked':True,'_revision':revision,'reason':'TEST restriction with audit'}
        with server.db() as con:con.execute("CREATE TRIGGER test_reject_user_audit BEFORE INSERT ON audit WHEN NEW.action='update-user' BEGIN SELECT RAISE(ABORT,'TEST audit failure'); END")
        try:self.req(path,'PUT',change,admin=True,expected=500)
        finally:
            with server.db() as con:con.execute('DROP TRIGGER test_reject_user_audit')
        self.assertEqual(self.req('/api/me',token=a['token'])['account']['_revision'],revision)
        self.req(path,'PUT',change,admin=True);self.req(path,'PUT',change,admin=True,expected=409)
        self.req('/api/me',token=a['token'],expected=401)
        with server.db() as con:
            detail=json.loads(con.execute("SELECT target FROM audit WHERE action='update-user' ORDER BY id DESC LIMIT 1").fetchone()[0])
            self.assertFalse(detail['before']['blocked']);self.assertTrue(detail['after']['blocked'])
            self.assertEqual(detail['changedFields'],[])
            self.assertNotIn('profile',detail['before']);self.assertNotIn('profile',detail['after'])

    def test_admin_profile_decode_does_not_hold_the_database_writer_lock(self):
        a=self.login('998909880003');entered=threading.Event();release=threading.Event();original=server.validate_account
        account=dict(a['account'],profile={'first':'TEST','last':'Concurrent','photo':None})
        def decoding(value):
            entered.set()
            if not release.wait(5):raise RuntimeError('TEST validation release timeout')
            return original(value)
        with patch.object(server,'validate_account',side_effect=decoding),ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(self.req,'/api/admin/users/'+a['userId'],'PUT',{'account':account,'_revision':a['account']['_revision'],'reason':'TEST pre-lock validation'},admin=True)
            try:
                self.assertTrue(entered.wait(5))
                with server.db() as con:
                    con.execute('PRAGMA busy_timeout=50');con.execute('BEGIN IMMEDIATE')
                    con.execute("INSERT OR REPLACE INTO attempts VALUES('TEST independent write',1,0)")
            finally:release.set()
            pending.result(timeout=5)

    def test_legacy_message_removal_is_reasoned_atomic_and_retry_does_not_duplicate_audit(self):
        a=self.login('998909880004');image=fixture_image('pink');text='PRIVATE TEST removal evidence'
        messages=self.req('/api/admin/users/'+a['userId']+'/messages','POST',{'sitter':'hoji','text':text,'image':image,'requestId':'TEST audit removal'},admin=True)['messages']
        identity=messages[-1]['id'];path='/api/admin/messages/'+identity
        self.req(path,'DELETE',{},admin=True,expected=400)
        self.req(path,'DELETE',{'reason':'TEST','actor':'forged'},admin=True,expected=400)
        self.req(path,'DELETE',{'reason':'TEST'},token=a['token'],expected=401)
        with server.db() as con:con.execute("CREATE TRIGGER test_reject_delete_audit BEFORE INSERT ON audit WHEN NEW.action='delete-message' BEGIN SELECT RAISE(ABORT,'TEST audit failure'); END")
        try:self.req(path,'DELETE',{'reason':'TEST remove'},admin=True,expected=500)
        finally:
            with server.db() as con:con.execute('DROP TRIGGER test_reject_delete_audit')
        with server.db() as con:
            row=con.execute('SELECT * FROM messages WHERE id=?',(identity,)).fetchone()
            self.assertEqual(row['text'],text);self.assertEqual(row['image'],image);self.assertFalse(row['deleted'])
            before=con.execute("SELECT COUNT(*) FROM audit WHERE action='delete-message'").fetchone()[0]
        self.req(path,'DELETE',{'reason':' TEST remove '},admin=True)
        self.req(path,'DELETE',{'reason':'TEST retry'},admin=True)
        with server.db() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM audit WHERE action='delete-message'").fetchone()[0],before+1)
            event=con.execute("SELECT actor,target FROM audit WHERE action='delete-message' ORDER BY id DESC LIMIT 1").fetchone()
            self.assertEqual(event['actor'],'admin');self.assertNotIn(text,event['target']);self.assertNotIn(image,event['target'])
            detail=json.loads(event['target']);self.assertEqual(detail['messageId'],identity);self.assertEqual(detail['reason'],'TEST remove')
            self.assertFalse(detail['before']['deleted']);self.assertTrue(detail['after']['deleted']);self.assertIsNone(detail['after']['imageSha256'])
        visible=self.req('/api/messages',token=a['token'])['messages'][-1]
        self.assertEqual(visible['text'],'Xabar o‘chirildi');self.assertIsNone(visible['image'])
    def test_validation_origin_and_revocation(self):
        a=self.login('998906666666')
        self.req('/api/messages','POST',{'sitter':'unknown','text':'x'},token=a['token'],expected=400)
        self.req('/api/messages','POST',{'sitter':'hoji','text':''},token=a['token'],expected=400)
        self.req('/api/me','PUT',a['account'],token=a['token'],expected=400)
        self.req('/api/admin/users',admin=True,origin='https://evil.example',expected=403)
        self.req('/api/auth/logout','POST',{},token=a['token'])
        self.req('/api/me',token=a['token'],expected=401)
    def test_photo_settings_and_persistence(self):
        a=self.login('998907777777')
        png=fixture_image()
        account=a['account'];account['profile']={'first':'Madina','last':'Test','photo':png}
        account['notifications']['chat']=False
        account['favorites']=['hoji'];account['language']='ru'
        account['addresses']=[{'id':'home','lat':41.3,'lon':69.2,'address':'Toshkent','label':'Uy'}]
        account['pets']=[{'id':'cat','name':'Momi','type':'Mushuk','photo':png}]
        account['support']=[{'id':'support1','text':'Yordam kerak'}]
        self.req('/api/me','PUT',account,token=a['token'])
        again=self.login('998907777777')
        self.assertEqual(again['account'],dict(server.validate_account(account),_revision=account['_revision']+1))
        with server.db() as con:
            con.execute('INSERT INTO messages(id,user_id,sitter,mine,text,time) VALUES(?,?,?,?,?,?)',('historical-image-chat',a['userId'],'hoji',0,'Old conversation','2020-01-01'))
        self.req('/api/messages','POST',{'sitter':'hoji','image':png},token=a['token'])
        self.assertEqual(self.req('/api/messages',token=a['token'])['messages'][-1]['image'],png)
        self.req('/api/messages','POST',{'sitter':'hoji','image':base64.b64encode(b'html').decode()},token=a['token'],expected=400)
    def test_static_admin_and_rate_limit(self):
        response=self.client.open(self.base+'/admin/')
        self.assertIn(b'loginForm',response.read())
        self.assertIn("frame-ancestors 'none'",response.headers['Content-Security-Policy'])
        for _ in range(15): self.req('/api/auth/login','POST',{'phone':'invalid','code':'0'},expected=401)
        self.req('/api/auth/login','POST',{'phone':'invalid','code':'0'},expected=429)

if __name__=='__main__': unittest.main()
