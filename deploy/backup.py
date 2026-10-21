#!/usr/bin/python3
from pathlib import Path
import sqlite3
from datetime import datetime, timezone, timedelta
root=Path('/var/backups/momiq'); root.mkdir(mode=0o700,exist_ok=True)
now=datetime.now(timezone.utc)
target=root/(now.strftime('%Y%m%dT%H%M%SZ')+'.sqlite3')
with sqlite3.connect('file:/var/lib/momiq/momiq.sqlite3?mode=ro',uri=True) as src, sqlite3.connect(target) as dst:
    src.backup(dst)
    assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
target.chmod(0o600)
for p in root.glob('*.sqlite3'):
    if datetime.fromtimestamp(p.stat().st_mtime,timezone.utc)<now-timedelta(days=14): p.unlink()
print('Database backup verified')
