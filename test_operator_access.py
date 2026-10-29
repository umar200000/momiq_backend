import hashlib
import json
import secrets
import sqlite3
import time
import unittest
from unittest.mock import patch

import manage_operators
import operator_access
import server
import test_admin_sessions as sessions
import test_catalog


class OperatorAccessTests(unittest.TestCase):
    setUp=sessions.AdminSessionTests.setUp
    save=sessions.AdminSessionTests.save
    review=sessions.AdminSessionTests.review
    stop_http=sessions.AdminSessionTests.stop_http
    req=sessions.AdminSessionTests.req
    admin=sessions.AdminSessionTests.admin
    login=sessions.AdminSessionTests.login

    def as_role(self,role):
        self.admin_token=secrets.token_hex(32)
        with server.db() as con:
            con.execute("UPDATE admin_permissions SET role=? WHERE username='TEST operator'",(role,))
            con.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(self.admin_token.encode()).hexdigest(),'TEST operator','admin',time.time()+3600))

    def test_separate_panels_cannot_fetch_private_data_or_cross_role_actions(self):
        cases={
            'support':('support',['users','listings','topups','bookings','disputes','platform-settings']),
            'finance':('topups',['users','listings','support','bookings','disputes','platform-settings']),
            'moderation':('listings',['users','topups','support','bookings','disputes','platform-settings']),
        }
        for role,(allowed,denied) in cases.items():
            self.as_role(role)
            identity=self.admin('/api/admin/me')
            self.assertEqual(identity['role'],role)
            self.assertIn(allowed,identity['panels'])
            self.admin('/api/admin/'+allowed)
            for target in denied:self.admin('/api/admin/'+target,status=403)
            for target in ['users/abc','bookings/'+'a'*32+'/videos','future-sensitive-endpoint']:
                self.admin('/api/admin/'+target,status=403)
            self.admin('/api/admin/users/abc','PUT',status=403)
            self.admin('/api/admin/platform-settings','PUT',status=403)
            self.admin('/api/admin/me','POST',status=403)
            self.req('/api/admin/me',status=401)
        self.as_role('administrator');self.admin('/api/admin/users')

    def test_role_change_disable_and_missing_grant_require_fresh_authentication(self):
        salt=secrets.token_hex(16)
        with server.db() as con:
            con.execute("UPDATE admins SET salt=?,hash=? WHERE username='TEST operator'",(salt,server.password_hash('TEST unique operator password',salt)))
        self.login('TEST unique operator password')
        with server.db() as con:con.execute("UPDATE admin_permissions SET role='finance' WHERE username='TEST operator'")
        self.admin('/api/admin/users',status=401)
        self.login('TEST unique operator password');self.admin('/api/admin/topups');self.admin('/api/admin/users',status=403)
        with server.db() as con:con.execute("UPDATE admin_permissions SET enabled=0 WHERE username='TEST operator'")
        self.admin('/api/admin/me',status=401);self.login('TEST unique operator password',401)
        with server.db() as con:con.execute("DELETE FROM admin_permissions WHERE username='TEST operator'")
        self.login('TEST unique operator password',401)
        self.req('/api/me')

    def test_allowlist_exact_paths_methods_and_new_endpoint_default_deny(self):
        book='a'*32
        examples={
            'support':[('GET',f'support/{book}/messages/1/image'),('POST',f'support/{book}')],
            'finance':[('GET',f'topups/{book}/history/0/receipt'),('GET',f'topups/{book}/receipt'),('GET',f'topups/{book}/corrections'),('POST',f'topups/{book}/review'),('POST',f'topups/{book}/corrections')],
            'moderation':[('GET','reviews/1/history'),('POST','reviews/1/moderate'),('GET','chat-reports/1/image'),('POST','chat-reports/1/review'),('GET','listings/abc/boarding'),('POST','listings/abc/boarding/review')],
        }
        for role,paths in examples.items():
            for method,path in paths:
                self.assertTrue(operator_access.permits(role,method,'/api/admin/'+path),(role,path))
                for other in examples:
                    if other!=role:self.assertFalse(operator_access.permits(other,method,'/api/admin/'+path))
                for bad in (path+'/extra','../'+path,'%2f'+path):self.assertFalse(operator_access.permits(role,method,'/api/admin/'+bad))
                self.assertFalse(operator_access.permits(role,'DELETE','/api/admin/'+path))
        self.assertFalse(operator_access.permits('owner','GET','/api/admin/users'))


class OperatorProvisioningTests(unittest.TestCase):
    def setUp(self):
        test_catalog.CatalogTests.setUp(self)
        self.password='Administrator TEST password'
        with server.db() as con:
            salt=secrets.token_hex(16)
            con.execute("UPDATE admins SET salt=?,hash=? WHERE username='admin'",(salt,server.password_hash(self.password,salt)))

    def change(self,username='support.one',role='support',enabled=True,password='Unique TEST operator password',actor='admin',actor_password=None):
        with server.db() as con:return manage_operators.change(con,actor,actor_password or self.password,username,role,enabled,'TEST access approval',password)

    def test_individual_password_roles_audit_and_session_revocation_are_atomic(self):
        self.assertTrue(self.change())
        with server.db() as con:
            self.assertEqual(operator_access.role_for(con,'support.one'),'support')
            con.execute("INSERT INTO sessions VALUES('TEST session','support.one','admin',9999999999)")
            old=con.execute('SELECT COUNT(*) FROM audit').fetchone()[0]
        self.assertFalse(self.change(password=None))
        with server.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM audit').fetchone()[0],old)
            self.assertTrue(con.execute("SELECT 1 FROM sessions WHERE hash='TEST session'").fetchone())
        self.change(role='finance',password=None)
        with server.db() as con:
            self.assertFalse(con.execute("SELECT 1 FROM sessions WHERE hash='TEST session'").fetchone())
            record=con.execute("SELECT actor,target FROM audit WHERE action='operator-access-change' ORDER BY id DESC").fetchone()
            payload=json.loads(record['target'])
            self.assertEqual(record['actor'],'admin');self.assertEqual(payload['before']['role'],'support');self.assertEqual(payload['after']['role'],'finance')
            self.assertFalse(payload['passwordChanged']);self.assertNotIn('password',record['target'].lower().replace('passwordchanged',''))
            self.assertNotIn(self.password,record['target'])
        self.change(role='finance',enabled=False,password=None)
        with server.db() as con:self.assertIsNone(operator_access.role_for(con,'support.one'))

    def test_wrong_actor_and_last_admin_removal_fail_without_changes(self):
        with self.assertRaisesRegex(ValueError,'authentication'):self.change(actor_password='wrong TEST password')
        self.change()
        with self.assertRaisesRegex(ValueError,'authentication'):
            self.change(username='finance.one',actor='support.one',actor_password='Unique TEST operator password')
        with self.assertRaisesRegex(ValueError,'last enabled'):self.change(username='admin',role='support',password=None)
        with self.assertRaisesRegex(ValueError,'last enabled'):self.change(username='admin',role='administrator',enabled=False,password=None)
        with server.db() as con:
            self.assertEqual(operator_access.role_for(con,'admin'),'administrator')
            self.assertFalse(con.execute("SELECT 1 FROM admins WHERE username='finance.one'").fetchone())

    def test_audit_failure_rolls_back_provisioning_and_empty_accounts_do_not_bootstrap(self):
        with server.db() as con:con.execute("CREATE TRIGGER test_reject_operator_audit BEFORE INSERT ON audit WHEN NEW.action='operator-access-change' BEGIN SELECT RAISE(ABORT,'TEST failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.change()
        with server.db() as con:
            self.assertFalse(con.execute("SELECT 1 FROM admins WHERE username='support.one'").fetchone())
            con.execute('DELETE FROM admins')
        server.setup()
        with server.db() as con:self.assertEqual(con.execute('SELECT COUNT(*) FROM admins').fetchone()[0],0)


if __name__=='__main__':unittest.main()
