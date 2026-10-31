"""Inspect or prune expired session hashes and throttling windows in bounded batches."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import time

from migrations import MIGRATIONS
from predeploy_backup import known_schema


def sweep(directory,mode,*,apply=False,limit=1000):
    if type(limit) is not int or not 1<=limit<=10000:
        raise ValueError('Invalid maintenance batch size')
    database=Path(directory).resolve(strict=True)/'momiq.sqlite3'
    uri=database.as_uri()+('?mode=rw' if apply else '?mode=ro')
    with closing(sqlite3.connect(uri,uri=True,timeout=2)) as con, con:
        con.execute('BEGIN IMMEDIATE' if apply else 'BEGIN')
        if known_schema(con,mode)!=MIGRATIONS[-1][0]:raise ValueError('Expected current instance schema')
        cutoff=time.time()
        report={}
        # Seek by rowid so a large active population cannot force a full scan
        # or starve expired rows later in the table. Each pass eventually wraps.
        for table,expiry in (('sessions','expires'),('attempts','reset')):
            key='maintenance.cursor.'+table
            saved=con.execute('SELECT value FROM runtime_metadata WHERE key=?',(key,)).fetchone()
            cursor=int(saved[0]) if saved else 0
            if not 0<=cursor<=2**63-1:raise ValueError('Invalid maintenance cursor')
            rows=con.execute(f'SELECT rowid,{expiry} FROM {table} WHERE rowid>? ORDER BY rowid LIMIT ?',
                             (cursor,limit)).fetchall()
            expired=[(rowid,) for rowid,end in rows if isinstance(end,(float,int)) and end<=cutoff]
            if apply:
                con.executemany(f'DELETE FROM {table} WHERE rowid=?',expired)
                following=rows[-1][0] if len(rows)==limit else 0
                if following!=cursor:
                    con.execute('INSERT INTO runtime_metadata VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                                (key,str(following)))
            report[table]={'scanned':len(rows),'expired':len(expired),'removed':len(expired) if apply else 0}
        return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',default=os.getenv('MOMIQ_DATA_DIR'))
    parser.add_argument('--mode',default=os.getenv('MOMIQ_ENV'),choices=('local','test','staging','production'))
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--limit',type=int,default=1000)
    args=parser.parse_args()
    if not args.data or not args.mode:parser.error('Provide the instance directory and mode')
    try:
        print(json.dumps(sweep(args.data,args.mode,apply=args.apply,limit=args.limit)))
    except (OSError,ValueError,sqlite3.Error):
        parser.exit(1,'Session maintenance failed\n')


if __name__=='__main__':
    main()
