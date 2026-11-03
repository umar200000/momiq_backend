import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import server
import session_maintenance


class SessionMaintenanceTests(unittest.TestCase):
    def test_dry_run_is_read_only_and_bounded_sweep_preserves_active_credentials_and_quotas(self):
        with TemporaryDirectory() as tmp,patch.object(server,'DATA',Path(tmp)),patch.object(server,'ENVIRONMENT','test'):
            server.setup()
            with server.db() as con:
                con.executemany('INSERT INTO sessions VALUES(?,?,?,?)',[
                    ('TEST active','owner','client',2000),('TEST expired','owner','client',999),('TEST admin','admin','admin',1000)])
                con.executemany('INSERT INTO attempts VALUES(?,?,?)',[
                    ('TEST address',15,2000),('TEST expired counter',5,1000),('TEST other counter',3,999)])
                before=list(con.iterdump())
            with patch.object(session_maintenance.time,'time',return_value=1000):
                report=session_maintenance.sweep(tmp,'test',limit=2)
                self.assertEqual(report['attempts'],{'scanned':2,'expired':1,'removed':0})
                self.assertNotIn('TEST',json.dumps(report))
                with self.assertRaises(ValueError):session_maintenance.sweep(tmp,'production',apply=True)
                with server.db() as con:self.assertEqual(list(con.iterdump()),before)
                first=session_maintenance.sweep(tmp,'test',apply=True,limit=2)
                second=session_maintenance.sweep(tmp,'test',apply=True,limit=2)
                for key in ('sessions','attempts'):
                    self.assertEqual(first[key]['removed'],1)
                    self.assertEqual(second[key]['removed'],1)
                third=session_maintenance.sweep(tmp,'test',apply=True,limit=2)
                self.assertEqual(third['sessions']['removed'],0)
                with server.db() as con:
                    self.assertEqual([tuple(r) for r in con.execute('SELECT hash,expires FROM sessions')],[('TEST active',2000)])
                    self.assertEqual([tuple(r) for r in con.execute('SELECT * FROM attempts')],[('TEST address',15,2000)])

    def test_missing_instance_is_not_created(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(sqlite3.OperationalError):session_maintenance.sweep(tmp,'test',apply=True)
            self.assertFalse((Path(tmp)/'momiq.sqlite3').exists())
