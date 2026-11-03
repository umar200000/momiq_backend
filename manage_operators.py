"""Local, password-confirmed operator provisioning; secrets never use CLI arguments."""
import argparse
import getpass
import hmac
import json
import re
import secrets
from contextlib import closing

import server
import operator_access


def change(con,actor,actor_password,username,role,enabled,reason,new_password=None):
    if not isinstance(username,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._@-]{2,99}',username):
        raise ValueError('Username must contain 3–100 letters, digits, dot, dash, underscore or @')
    if role not in operator_access.ROLES or type(enabled) is not bool:raise ValueError('Invalid role or enabled flag')
    if not isinstance(reason,str) or not 10<=len(reason.strip())<=1000:raise ValueError('A 10–1000 character reason is required')
    if new_password is not None and (not isinstance(new_password,str) or not 14<=len(new_password)<=200 or not new_password.strip()):
        raise ValueError('Use a unique password of 14–200 characters')
    con.execute('BEGIN IMMEDIATE')
    try:
        operator=con.execute('SELECT * FROM admins WHERE username=?',(actor,)).fetchone()
        if (operator_access.role_for(con,actor)!='administrator' or not operator
                or not hmac.compare_digest(operator['hash'],server.password_hash(actor_password,operator['salt']))):
            raise ValueError('Administrator authentication failed')
        existing=con.execute('SELECT * FROM admins WHERE username=?',(username,)).fetchone()
        grant=con.execute('SELECT role,enabled FROM admin_permissions WHERE username=?',(username,)).fetchone()
        before={'role':grant['role'],'enabled':bool(grant['enabled'])} if grant else None
        if existing is None and new_password is None:raise ValueError('A password is required for a new operator')
        if before=={'role':'administrator','enabled':True} and (role!='administrator' or not enabled):
            count=con.execute("SELECT COUNT(*) FROM admin_permissions p JOIN admins a ON a.username=p.username WHERE p.role='administrator' AND p.enabled=1").fetchone()[0]
            if count<=1:raise ValueError('Cannot remove the last enabled administrator')
        after={'role':role,'enabled':enabled}
        if before==after and new_password is None:
            con.rollback();return False
        if new_password is not None:
            salt=secrets.token_hex(16);digest=server.password_hash(new_password,salt)
            if existing:con.execute('UPDATE admins SET salt=?,hash=? WHERE username=?',(salt,digest,username))
            else:con.execute('INSERT INTO admins VALUES(?,?,?)',(username,salt,digest))
        con.execute('INSERT INTO admin_permissions VALUES(?,?,?) ON CONFLICT(username) DO UPDATE SET role=excluded.role,enabled=excluded.enabled',(username,role,int(enabled)))
        detail=json.dumps({'username':username,'before':before,'after':after,'passwordChanged':new_password is not None,'reason':reason.strip()},ensure_ascii=True)
        con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',(actor,'operator-access-change',detail,server.now()))
        con.commit();return True
    except BaseException:
        con.rollback();raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('username')
    parser.add_argument('--actor',required=True,help='Existing enabled administrator username')
    parser.add_argument('--role',required=True,choices=operator_access.ROLES)
    parser.add_argument('--disable',action='store_true')
    parser.add_argument('--reset-password',action='store_true',help='Required when creating a new operator')
    parser.add_argument('--reason',required=True)
    args=parser.parse_args()
    if not (server.DATA/'momiq.sqlite3').is_file():parser.error('Initialize and migrate the intended database before provisioning')
    actor_password=getpass.getpass('Current administrator password: ')
    new_password=None
    if args.reset_password:
        new_password=getpass.getpass('New operator password: ')
        if new_password!=getpass.getpass('Repeat new operator password: '):parser.error('Passwords differ')
    with closing(server.db()) as con:
        try:changed=change(con,args.actor,actor_password,args.username,args.role,not args.disable,args.reason,new_password)
        except ValueError as error:parser.error(str(error))
    print('Operator access saved; old sessions revoked where credentials or permissions changed.' if changed else 'No change.')


if __name__=='__main__':main()
