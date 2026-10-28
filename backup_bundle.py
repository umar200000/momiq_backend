"""Verified SQLite snapshot plus its referenced immutable private media.

Never overwrites a backup; publish only after database and media verification.
Offsite storage, coordinated media retirement and retention are operator policy.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
from migrations import backup_database


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def references(database):
    with closing(sqlite3.connect(f'{database.as_uri()}?mode=ro',uri=True)) as con:
        if con.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or con.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Backup database integrity failed')
        table=con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='booking_videos'").fetchone()
        if not table:return []
        result=[]
        for identity,video,poster in con.execute('SELECT id,video_hash,poster_hash FROM booking_videos ORDER BY id'):
            if not re.fullmatch(r'[a-f0-9]{32}',identity):raise ValueError('Invalid stored video ID')
            for name,checksum in [('playback.mp4',video),('poster.jpg',poster)]:
                if not re.fullmatch(r'[a-f0-9]{64}',checksum):raise ValueError('Invalid stored video hash')
                result.append((f'care-videos/{identity}/{name}',checksum))
        return result


def verify(folder):
    folder=Path(folder).resolve()
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    database=folder/'momiq.sqlite3'
    if manifest.get('version')!=1 or digest(database)!=manifest.get('databaseSha256'):
        raise ValueError('Backup manifest/database mismatch')
    expected=references(database)
    if manifest.get('files')!=[{'path':path,'sha256':checksum} for path,checksum in expected]:
        raise ValueError('Backup media manifest mismatch')
    for relative,checksum in expected:
        source=folder/relative
        if not source.resolve().is_relative_to(folder) or digest(source)!=checksum:
            raise ValueError('Backup video missing or corrupt')
    return {'database':'ok','mediaFiles':len(expected)}


def create(data, target):
    data,target=Path(data).resolve(),Path(target).absolute()
    if target.exists() or target.is_symlink():raise ValueError('Backup destination already exists')
    target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with tempfile.TemporaryDirectory(prefix='.momiq-backup-',dir=target.parent) as temporary:
        staging=Path(temporary)/'bundle';staging.mkdir(mode=0o700)
        database=staging/'momiq.sqlite3'
        backup_database(data/'momiq.sqlite3',database)
        database.chmod(0o600)
        expected=references(database)
        for relative,checksum in expected:
            source=data/relative
            if not source.resolve().is_relative_to(data):raise ValueError('Media path escapes instance')
            destination=staging/relative;destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            shutil.copyfile(source,destination);destination.chmod(0o600)
            if digest(destination)!=checksum:raise ValueError('Source video missing or corrupt')
        manifest={'version':1,'created':datetime.now(timezone.utc).isoformat(),
                  'databaseSha256':digest(database),'files':[{'path':p,'sha256':h} for p,h in expected]}
        (staging/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        (staging/'manifest.json').chmod(0o600)
        result=verify(staging)
        if target.exists():raise ValueError('Backup destination appeared during copy')
        staging.rename(target)
        return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--data-dir',type=Path)
    group.add_argument('--verify',type=Path)
    parser.add_argument('--destination',type=Path)
    args=parser.parse_args()
    if args.data_dir and args.destination is None:parser.error('--destination is required')
    print(json.dumps(verify(args.verify) if args.verify else create(args.data_dir,args.destination)))
