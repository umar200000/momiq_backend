import hashlib
import json
import secrets
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import server
import test_admin_bookings as fixtures


class AdminSessionTests(unittest.TestCase):
    setUp=fixtures.AdminBookingTests.setUp
    save=fixtures.AdminBookingTests.save
    review=fixtures.AdminBookingTests.review
    stop_http=fixtures.AdminBookingTests.stop_http
    req=fixtures.AdminBookingTests.req
    admin=fixtures.AdminBookingTests.admin

    def login(self,password,status=200,username='TEST operator'):
        request=Request(self.base+'/api/admin/login',data=json.dumps({'username':username,'password':password}).encode(),
                        headers={'Content-Type':'application/json'})
        try: response=urlopen(request)
        except HTTPError as error: response=error
        with response:
            self.assertEqual(response.status,status)
            cookie=response.headers.get('Set-Cookie')
            if status==200:
                self.assertIn('HttpOnly',cookie)
                self.assertIn('SameSite=Strict',cookie)
                self.admin_token=cookie.split(';')[0].split('=',1)[1]
            else:self.assertIsNone(cookie)

    def test_login_hashing_allows_revocation_and_unknown_names_get_one_hash(self):
        salt = secrets.token_hex(16)
        original = server.password_hash
        digest = original('TEST before rotation', salt)
        updated = original('TEST after rotation', salt)
        with server.db() as con:
            con.execute("UPDATE admins SET salt=?,hash=? WHERE username='TEST operator'", (salt, digest))
        def rotate_during_check(value, checked_salt):
            with server.db() as writer:
                writer.execute('PRAGMA busy_timeout=50')
                writer.execute("UPDATE admins SET hash=? WHERE username='TEST operator'", (updated,))
            return original(value, checked_salt)
        with patch.object(server, 'password_hash', side_effect=rotate_during_check) as derive:
            self.login('TEST before rotation', status=401)
            self.assertEqual(derive.call_count, 1)
        with patch.object(server, 'password_hash', wraps=original) as derive:
            self.login('TEST before rotation', status=401, username='unknown TEST operator')
            self.assertEqual(derive.call_count, 1)
        self.login('TEST after rotation')

    def test_delete_recreate_and_orphan_tokens_never_restore_admin_access(self):
        self.admin('/api/admin/users')
        old_token=self.admin_token
        with server.db() as con:con.execute("DELETE FROM admins WHERE username='TEST operator'")
        self.admin('/api/admin/users',status=401)
        with server.db() as con:
            self.assertFalse(con.execute("SELECT 1 FROM sessions WHERE role='admin' AND user_id='TEST operator'").fetchone())
            # An old orphan row is denied even if it predates the trigger.
            con.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(old_token.encode()).hexdigest(),'TEST operator','admin',time.time()+3600))
        self.admin('/api/admin/users',status=401)
        with server.db() as con:con.execute("INSERT INTO admins VALUES('TEST operator','TEST salt','disabled')")
        self.admin('/api/admin/users',status=401)
        self.req('/api/me')  # Unrelated client sessions are preserved.

    def test_password_change_and_replacement_revoke_all_old_sessions(self):
        salt=secrets.token_hex(16)
        with server.db() as con:
            con.execute("UPDATE admins SET salt=?,hash=? WHERE username='TEST operator'",(salt,server.password_hash('old TEST password',salt)))
        self.admin('/api/admin/users',status=401)
        self.login('old TEST password');first=self.admin_token
        self.login('old TEST password');second=self.admin_token
        with server.db() as con:
            con.execute("UPDATE admins SET hash=? WHERE username='TEST operator'",(server.password_hash('new TEST password',salt),))
        for token in (first,second):
            self.admin_token=token;self.admin('/api/admin/users',status=401)
        self.login('old TEST password',401)
        self.login('new TEST password');self.admin('/api/admin/users')
        # A no-op credential update does not unexpectedly sign out operators.
        with server.db() as con:con.execute("UPDATE admins SET hash=hash WHERE username='TEST operator'")
        self.admin('/api/admin/users')
        with server.db() as con:con.execute("INSERT OR REPLACE INTO admins VALUES('TEST operator',?,?)",(salt,server.password_hash('replacement TEST password',salt)))
        self.admin('/api/admin/users',status=401)
        with server.db() as con:con.execute("INSERT OR IGNORE INTO admin_permissions VALUES('TEST operator','administrator',1)")
        self.login('replacement TEST password');self.admin('/api/admin/users')

    def test_session_roles_and_expiry_are_not_interchangeable(self):
        real_admin_token=self.admin_token
        self.admin_token=self.tokens['customer'];self.admin('/api/admin/users',status=401)
        self.tokens['customer']=real_admin_token;self.req('/api/me',status=401)
        self.admin_token=real_admin_token
        with server.db() as con:con.execute("UPDATE sessions SET expires=? WHERE role='admin'",(time.time()-1,))
        self.admin('/api/admin/users',status=401)


if __name__=='__main__':unittest.main()
