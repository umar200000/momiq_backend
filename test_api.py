import base64
import http.cookiejar
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import Request, build_opener, HTTPCookieProcessor
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
import server

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
    def test_roles_and_server_listings(self):
        login = self.req('/api/auth/login','POST',{'phone':'998909991122','code':'111111','role':'sitter'})
        token, uid = login['token'],login['userId']
        users = self.req('/api/admin/users',admin=True)['users']
        self.assertEqual(next(u for u in users if u['id']==uid)['roles'],['sitter'])
        payload = {'housing':'house','listings':[{'type':'boarding','pets':['cat'],'price':100000,'capacity':2,'location':{'lat':41.3,'lon':69.2,'address':'Test address'},'active':True}]}
        self.req('/api/me/listings','PUT',payload,token=token,expected=403)
        account=login['account'];account['profile'].update(first='Sitter',last='Test')
        account['sitterProfile']={'years':1,'about':'','homePhotos':[],'housing':'house'}
        self.req('/api/me','PUT',account,token=token)
        self.req('/api/me/listings','PUT',payload,token=token)
        self.assertEqual(self.req('/api/me/listings',token=token),payload)
        other=self.login('998909991133')
        self.assertEqual(self.req('/api/me/listings',token=other['token'])['listings'],[])
        self.req('/api/admin/listings',token=token,expected=401)
        ads=self.req('/api/admin/listings',admin=True)['listings']
        self.assertEqual(next(a for a in ads if a['userId']==uid)['price'],100000)
        bad=json.loads(json.dumps(payload));bad['housing']='apartment'
        self.req('/api/me/listings','PUT',bad,token=token,expected=400)
        bad=json.loads(json.dumps(payload));bad['listings'][0]['price']=True
        self.req('/api/me/listings','PUT',bad,token=token,expected=400)
        bad=json.loads(json.dumps(payload));bad['listings'].append(dict(bad['listings'][0],type='personal',capacity=None))
        self.req('/api/me/listings','PUT',bad,token=token,expected=400)
        self.assertEqual(self.req('/api/me/listings',token=token),payload)
        self.req('/api/auth/logout','POST',{},token=token)
        again=self.req('/api/auth/login','POST',{'phone':'998909991122','code':'111111','role':'customer'})
        self.assertEqual(self.req('/api/me/listings',token=again['token']),payload)
        users=self.req('/api/admin/users',admin=True)['users']
        self.assertEqual(next(u for u in users if u['id']==uid)['roles'],['customer','sitter'])
        server.setup()
        with server.db() as con:
            self.assertEqual(server.roles_for(con,uid),['customer','sitter'])

    def test_catalog_contains_only_database_records(self):
        self.assertEqual(self.req('/api/sitters')['sitters'], [{'id':'hoji','name':'Test sitter'}])
        with server.db() as con:
            con.execute("UPDATE sitters SET active=0 WHERE id='hoji'")
        try:
            self.assertEqual(self.req('/api/sitters')['sitters'], [])
            self.assertEqual(self.req('/api/admin/users',admin=True)['sitters'], {})
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
        self.req('/api/admin/users/'+a['userId'],'PUT',{'account':stale,'_revision':stale['_revision']},admin=True,expected=409)
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
    def test_chat_reply_isolation_and_idempotency(self):
        a=self.login('998903333333');b=self.login('998904444444')
        message={'sitter':'hoji','text':'Salom','requestId':'once'}
        self.req('/api/messages','POST',message,token=a['token'])
        self.req('/api/messages','POST',message,token=a['token'])
        self.assertEqual(len(self.req('/api/messages',token=a['token'])['messages']),1)
        self.assertEqual(self.req('/api/messages',token=b['token'])['messages'],[])
        data=self.req('/api/admin/users/'+a['userId']+'/messages','POST',{'sitter':'hoji','text':'Salom, javob','requestId':'reply'},admin=True)
        self.assertFalse(data['messages'][-1]['mine'])
        self.req('/api/admin/messages/'+data['messages'][-1]['id'],'DELETE',admin=True)
        self.assertEqual(self.req('/api/messages',token=a['token'])['messages'][-1]['text'],'Xabar o‘chirildi')
    def test_admin_block_and_unblock(self):
        a=self.login('998905555555')
        self.req('/api/admin/users/'+a['userId'],'PUT',{'blocked':True,'_revision':a['account']['_revision']},admin=True)
        self.req('/api/me',token=a['token'],expected=401)
        self.req('/api/auth/login','POST',{'phone':'998905555555','code':'111111'},expected=403)
        self.req('/api/admin/users/'+a['userId'],'PUT',{'blocked':False,'_revision':a['account']['_revision']+1},admin=True)
        self.req('/api/me',token=a['token'],expected=401)
        fresh=self.login('998905555555')
        self.req('/api/me',token=fresh['token'])
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
        png=base64.b64encode(bytes.fromhex('89504e470d0a1a0a')+b'example').decode()
        account=a['account'];account['profile']={'first':'Madina','last':'Test','photo':png}
        account['notifications']['chat']=False
        account['favorites']=['hoji'];account['language']='ru'
        account['addresses']=[{'id':'home','lat':41.3,'lon':69.2,'address':'Toshkent','label':'Uy'}]
        account['pets']=[{'id':'cat','name':'Momi','type':'Mushuk','photo':png}]
        account['support']=[{'id':'support1','text':'Yordam kerak'}]
        self.req('/api/me','PUT',account,token=a['token'])
        again=self.login('998907777777')
        self.assertEqual(again['account'],dict(account,_revision=account['_revision']+1))
        self.req('/api/messages','POST',{'sitter':'hoji','image':png},token=a['token'])
        self.assertEqual(self.req('/api/messages',token=a['token'])['messages'][0]['image'],png)
        self.req('/api/messages','POST',{'sitter':'hoji','image':base64.b64encode(b'html').decode()},token=a['token'],expected=400)
    def test_static_admin_and_rate_limit(self):
        response=self.client.open(self.base+'/admin/')
        self.assertIn(b'loginForm',response.read())
        self.assertIn("frame-ancestors 'none'",response.headers['Content-Security-Policy'])
        for _ in range(15): self.req('/api/auth/login','POST',{'phone':'invalid','code':'0'},expected=401)
        self.req('/api/auth/login','POST',{'phone':'invalid','code':'0'},expected=429)

if __name__=='__main__': unittest.main()
