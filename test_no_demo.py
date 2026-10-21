import json
import sqlite3
import unittest
from deploy.cleanup_demo_data import clean

class CleanupTests(unittest.TestCase):
    def test_cleanup_preserves_actual_accounts_and_is_idempotent(self):
        con = sqlite3.connect(':memory:')
        con.executescript("CREATE TABLE users(id,phone,account); CREATE TABLE messages(user_id,sitter); CREATE TABLE sessions(user_id,role);")
        real = {'profile': {'first':'Actual','last':'User'}, 'favorites':['hoji','real-sitter'], 'pets':[{'id':'real-pet'}]}
        demo = {'profile': {'first':'Sinov','last':'Mijoz'}}
        con.executemany('INSERT INTO users VALUES(?,?,?)', [('real','998901234567',json.dumps(real)),('demo','998900000001',json.dumps(demo))])
        con.executemany('INSERT INTO messages VALUES(?,?)', [('real','hoji'),('real','real-sitter'),('demo','hoji')])
        con.execute("INSERT INTO sessions VALUES('demo','client')")
        self.assertEqual(clean(con), (2,1))
        kept = json.loads(con.execute('SELECT account FROM users').fetchone()[0])
        self.assertEqual(kept['pets'], real['pets'])
        self.assertEqual(kept['favorites'], ['real-sitter'])
        self.assertEqual(con.execute('SELECT sitter FROM messages').fetchall(), [('real-sitter',)])
        self.assertEqual(clean(con), (0,0))
        con.close()
