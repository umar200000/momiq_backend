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
        self.assertEqual(response.status,expected)
        return json.loads(response.read())
    def login(self,phone='998901111111'):
        return self.req('/api/auth/login','POST',{'phone':phone,'code':'111111'})
    def test_native_access_and_parser_logs_omit_request_data(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from socket import create_connection
        output = StringIO()
        with redirect_stdout(output):
            self.req('/api/health?address=private-marker', token='private-marker')
            with create_connection(self.http.server_address, timeout=5) as client:
                client.sendall(b'private-marker malformed request line\r\n\r\n')
                while client.recv(4096):
                    pass
        self.assertEqual(output.getvalue().splitlines(),
                         ['http status 200', 'http diagnostic', 'http status 400'])
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
        self.req('/api/admin/users/'+a['userId'],'PUT',{'blocked':True},admin=True)
        self.req('/api/me',token=a['token'],expected=403)
        self.req('/api/auth/login','POST',{'phone':'998905555555','code':'111111'},expected=403)
        self.req('/api/admin/users/'+a['userId'],'PUT',{'blocked':False},admin=True)
        self.req('/api/me',token=a['token'])
    def test_parallel_chat_retries_and_conflicting_text(self):
        from concurrent.futures import ThreadPoolExecutor
        a=self.login('998900010151')
        message={'sitter':'hoji','text':'Original','requestId':'test-concurrent'}
        with ThreadPoolExecutor(4) as pool:
            results=list(pool.map(lambda _:self.req('/api/messages','POST',message,token=a['token']),range(4)))
        self.assertTrue(all(len(r['messages'])==1 for r in results))
        self.assertEqual(len({r['messages'][0]['id'] for r in results}),1)
        self.req('/api/messages','POST',{**message,'text':'Different'},token=a['token'],expected=409)
        self.assertEqual(self.req('/api/messages',token=a['token'])['messages'][0]['text'],'Original')

    def test_revoked_sender_and_newly_blocked_recipient_cannot_commit_message(self):
        from unittest.mock import patch
        a=self.login('998900010152')
        message={'sitter':'hoji','text':'Test','requestId':'test-revoked'}
        def revoke(_):
            with server.db() as other: other.execute('DELETE FROM sessions WHERE user_id=?',(a['userId'],))
        def block(_):
            with server.db() as other: other.execute('UPDATE users SET blocked=1 WHERE id=?',(a['userId'],))
        with patch.object(server,'photo',revoke):
            self.req('/api/messages','POST',message,token=a['token'],expected=401)
        with patch.object(server,'photo',block):
            self.req('/api/admin/users/'+a['userId']+'/messages','POST',message,admin=True,expected=409)
        with server.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM messages WHERE user_id=?',(a['userId'],)).fetchone()[0],0)
            self.assertFalse(con.execute("SELECT 1 FROM audit WHERE action='reply' AND target=?",(a['userId'],)).fetchone())
    def test_validation_origin_and_revocation(self):
        a=self.login('998906666666')
        self.req('/api/messages','POST',{'sitter':'unknown','text':'x'},token=a['token'],expected=400)
        self.req('/api/messages','POST',{'sitter':'hoji','text':''},token=a['token'],expected=400)
        self.req('/api/me','PUT',a['account'],token=a['token'],expected=400)
        self.req('/api/admin/users',admin=True,origin='https://evil.example',expected=403)
        self.req('/api/auth/logout','POST',{},token=a['token'])
        self.req('/api/me',token=a['token'],expected=401)

    def test_profile_export_uses_session_owner_and_excludes_media_and_internal_fields(self):
        path='/api/me/profile-export'
        owner=self.login('998900010811')
        other=self.login('998900010812')
        data=owner['account']
        data.update(profile={'first':'Exported','last':'TEST','photo':'PRIVATE photo'},
                    addresses=[{'id':'test','address':'TEST outside fixture','apartment':'Gate 1','unknown':'PRIVATE'}],
                    pets=[{'id':'pet','name':'Cat','photo':'PRIVATE image','notes':{'file':'PRIVATE'}}],
                    sitterProfile={'housing':'house','years':3,'about':'Owner','homePhotos':['PRIVATE']},
                    support=[{'text':'PRIVATE message'}],session='PRIVATE token')
        with server.db() as con:
            con.execute('UPDATE users SET account=? WHERE id=?',(json.dumps(data),owner['userId']))
        self.req(path,expected=401)
        self.req(path,admin=True,expected=401)
        self.req(path+'?owner='+owner['userId'],token=other['token'],expected=400)
        self.req(path,'POST',{},token=owner['token'],expected=405)
        output=self.req(path,token=owner['token'])
        self.assertEqual((output['format'],output['ownerId'],output['profile']['phone']),
                         ('momiq-profile-v1',owner['userId'],'998900010811'))
        self.assertEqual(output['addresses'][0]['apartment'],'Gate 1')
        self.assertEqual(output['pets'],[{'id':'pet','name':'Cat'}])
        self.assertNotIn('PRIVATE',json.dumps(output))
        self.assertNotIn('Exported',json.dumps(self.req(path,token=other['token'])))
        with server.db() as con:
            con.execute('UPDATE users SET blocked=1 WHERE id=?',(owner['userId'],))
        self.req(path,token=owner['token'],expected=403)

    def test_approved_city_and_province_addresses_and_sitter_listing(self):
        from unittest.mock import patch
        import service_area
        conf=service_area.configuration({'MOMIQ_ENV':'production'})
        owner=self.login('998900010291')
        other=self.login('998900010292')
        profile=owner['account']
        profile['profile'].update(first='TEST',last='address')
        profile['sitterProfile']={'housing':'house'}
        with patch.object(server,'AREA',service_area.load(conf)):
            for lon,lat in [(69.2797,41.3112),(69.5822,41.4689),(70.1436,41.0167),(69.269,40.217)]:
                address={'id':'one','label':'TEST','address':'private road','apartment':'Gate 7','lat':lat,'lon':lon}
                profile['addresses']=[address]
                saved=self.req('/api/me','PUT',profile,token=owner['token'])
                self.assertEqual(saved['account']['addresses'],[address])
            outside={**address,'lon':66.9749,'lat':39.6542}
            rejected={**profile,'addresses':[outside]}
            self.req('/api/me','PUT',rejected,token=owner['token'],expected=400)
            self.req('/api/admin/users/'+owner['userId'],'PUT',{'account':rejected},admin=True,expected=400)
            self.assertEqual(self.req('/api/me',token=owner['token'])['account']['addresses'],[address])
            self.assertEqual(self.req('/api/me',token=other['token'])['account']['addresses'],[])
            listing={'type':'personal','pets':['cat'],'price':50000,'active':True,'location':outside}
            self.req('/api/me/listings','PUT',{'housing':'house','listings':[listing]},token=owner['token'],expected=400)
            listing['location']=address
            self.req('/api/me/listings','PUT',{'housing':'house','listings':[listing]},token=owner['token'])
            profile['addresses']=[]
            self.assertEqual(self.req('/api/me','PUT',profile,token=owner['token'])['account']['addresses'],[])

    def test_revocation_during_profile_validation_prevents_write(self):
        from unittest.mock import patch
        a=self.login('998900011041')
        changed={**a['account'],'profile':{'first':'Attempt','last':'TEST'}}
        validate=server.validate_account
        def revoke(data):
            result=validate(data)
            with server.db() as writer:
                writer.execute('DELETE FROM sessions WHERE user_id=?',(a['userId'],))
            return result
        with patch.object(server,'validate_account',revoke):
            self.req('/api/me','PUT',changed,token=a['token'],expected=401)
        with server.db() as con:
            saved=json.loads(con.execute('SELECT account FROM users WHERE id=?',(a['userId'],)).fetchone()[0])
            self.assertEqual(saved,a['account'])

    def test_removed_sitter_profile_cannot_publish_after_validation(self):
        from unittest.mock import patch
        a=self.login('998900011042')
        profile={**a['account'],'profile':{'first':'Sitter','last':'TEST'},'sitterProfile':{'housing':'house'}}
        self.req('/api/me','PUT',profile,token=a['token'])
        validate=server.validate_listings
        def remove_profile(data):
            result=validate(data)
            with server.db() as writer:
                writer.execute("UPDATE users SET account=json_set(account,'$.sitterProfile',NULL) WHERE id=?",(a['userId'],))
            return result
        with patch.object(server,'validate_listings',remove_profile):
            self.req('/api/me/listings','PUT',{'housing':'house','listings':[]},token=a['token'],expected=403)
        with server.db() as con:
            self.assertFalse(con.execute('SELECT 1 FROM listings WHERE user_id=?',(a['userId'],)).fetchone())

    def test_operator_edits_only_changed_profile_fields_and_rejects_stale_values(self):
        a = self.login('998900011056')
        uid = a['userId']
        path = '/api/admin/users/'+uid+'/profile'
        saved = {**a['account'], 'language':'en', 'profile':{'first':'Alice','last':'New','photo':None}}
        with server.db() as con:
            con.execute('UPDATE users SET account=?,blocked=1 WHERE id=?',(json.dumps(saved),uid))
        edit = {'before':{'first':'Alice'},'after':{'first':'Anna'}}
        self.req(path,'PUT',edit,admin=True)
        self.req(path,'PUT',edit,admin=True)
        self.req(path,'PUT',{'before':{'first':'Alice'},'after':{'first':'Other'}},admin=True,expected=409)
        self.req(path,'PUT',{**edit,'blocked':False},admin=True,expected=400)
        self.req(path,'PUT',{'before':{'last':'New'},'after':{'last':''}},admin=True,expected=400)
        self.req(path,'PUT',{'before':{'blocked':True},'after':{'blocked':False}},admin=True,expected=400)
        self.req(path,'PUT',edit,token=a['token'],expected=401)
        with server.db() as con:
            account,blocked = con.execute('SELECT account,blocked FROM users WHERE id=?',(uid,)).fetchone()
            saved['profile']['first'] = 'Anna'
            self.assertEqual((json.loads(account),blocked),(saved,1))
            self.assertEqual(con.execute("SELECT count(*) FROM audit WHERE action='update-user' AND target=?",(uid,)).fetchone()[0],1)

    def test_admin_profile_only_edit_keeps_blocked_account_blocked(self):
        a=self.login('998900011043')
        path='/api/admin/users/'+a['userId']
        self.req(path,'PUT',{'blocked':True},admin=True)
        profile={**a['account'],'profile':{'first':'Edited','last':'TEST'}}
        self.req(path,'PUT',{'account':profile,'blocked':False},admin=True,expected=409)
        self.req(path,'PUT',{'role':'admin','blocked':False},admin=True,expected=400)
        self.req(path,'PUT',{},admin=True,expected=400)
        self.req(path,'PUT',{'account':profile},admin=True)
        self.req('/api/me',token=a['token'],expected=403)

    def test_admin_block_only_edit_keeps_concurrent_profile_update(self):
        from unittest.mock import patch
        a=self.login('998900011044')
        original=server.Handler.body
        def edit_during_request(handler):
            data=original(handler)
            with server.db() as writer:
                writer.execute("UPDATE users SET account=json_set(account,'$.profile.first','New name') WHERE id=?",(a['userId'],))
            return data
        with patch.object(server.Handler,'body',edit_during_request):
            self.req('/api/admin/users/'+a['userId'],'PUT',{'blocked':True},admin=True)
        with server.db() as con:
            row=con.execute("SELECT json_extract(account,'$.profile.first'),blocked FROM users WHERE id=?",(a['userId'],)).fetchone()
            self.assertEqual(tuple(row),('New name',1))

    def test_repeated_block_request_records_one_transition(self):
        from concurrent.futures import ThreadPoolExecutor
        a = self.login('998900011057')
        path = '/api/admin/users/'+a['userId']
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _:self.req(path,'PUT',{'blocked':True},admin=True),range(2)))
        self.assertEqual(results,[{'ok':True}]*2)
        self.req(path,'PUT',{'blocked':False},admin=True)
        self.req(path,'PUT',{'blocked':False},admin=True)
        with server.db() as con:
            self.assertEqual(con.execute('SELECT blocked FROM users WHERE id=?',(a['userId'],)).fetchone()[0],0)
            self.assertEqual(con.execute("SELECT count(*) FROM audit WHERE action='update-user' AND target=?",
                                         (a['userId'],)).fetchone()[0],2)

    def test_revoked_operator_cannot_finish_profile_edit_or_leave_audit(self):
        from unittest.mock import patch
        a=self.login('998900011045')
        original=server.validate_account
        def revoke(data):
            with server.db() as writer:
                writer.execute("DELETE FROM sessions WHERE role='admin'")
            return original(data)
        with patch.object(server,'validate_account',revoke):
            self.req('/api/admin/users/'+a['userId'],'PUT',
                     {'account':{**a['account'],'profile':{'first':'Attempt','last':'TEST'}}},admin=True,expected=401)
        with server.db() as con:
            self.assertEqual(json.loads(con.execute('SELECT account FROM users WHERE id=?',(a['userId'],)).fetchone()[0]),a['account'])
            self.assertFalse(con.execute("SELECT 1 FROM audit WHERE action='update-user' AND target=?",(a['userId'],)).fetchone())
    def test_photo_settings_and_persistence(self):
        a=self.login('998907777777')
        from io import BytesIO
        from PIL import Image
        buffer=BytesIO(); Image.new('RGB',(2,2)).save(buffer,format='PNG')
        png=base64.b64encode(buffer.getvalue()).decode()
        account=a['account'];account['profile']={'first':'Madina','last':'Test','photo':png}
        account['notifications']['chat']=False
        account['favorites']=['hoji'];account['language']='ru'
        account['addresses']=[{'id':'home','lat':41.3,'lon':69.2,'address':'Toshkent','label':'Uy'}]
        account['pets']=[{'id':'cat','name':'Momi','type':'Mushuk','photo':png}]
        account['support']=[{'id':'support1','text':'Yordam kerak'}]
        self.req('/api/me','PUT',account,token=a['token'])
        again=self.login('998907777777')
        self.assertEqual(again['account'],account)
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
