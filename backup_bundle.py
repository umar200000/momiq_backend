"""Verified SQLite snapshot plus its referenced immutable private media.

Never overwrites a backup; publish only after database and media verification.
Offsite storage, coordinated media retirement and retention are operator policy.
"""
from contextlib import closing
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile
from migrations import backup_database
import media_maintenance
import video_media
from video_retention_policy import expires_at


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def references(database, now):
    with closing(sqlite3.connect(f'{database.as_uri()}?mode=ro&immutable=1',uri=True)) as con:
        con.row_factory=sqlite3.Row
        if con.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or con.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Backup database integrity failed')
        table=con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='booking_videos'").fetchone()
        if not table:return []
        result=[]
        retired=con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='video_retirements'").fetchone()
        for identity,video,poster,booking in con.execute('SELECT id,video_hash,poster_hash,booking_id FROM booking_videos ORDER BY id'):
            expiry=expires_at(con,booking)
            if expiry is not None and expiry<=now:continue
            if retired and con.execute('SELECT 1 FROM video_retirements WHERE video_id=?',(identity,)).fetchone():continue
            if not re.fullmatch(r'[a-f0-9]{32}',identity):raise ValueError('Invalid stored video ID')
            for name,checksum in [('playback.mp4',video),('poster.jpg',poster)]:
                if not re.fullmatch(r'[a-f0-9]{64}',checksum):raise ValueError('Invalid stored video hash')
                result.append((f'care-videos/{identity}/{name}',checksum))
        return result


def bundle_file(folder, relative):
    """Resolve a known bundle member, refusing redirected or special files."""
    path = folder
    components = Path(relative).parts
    if not components:
        raise ValueError('Empty backup member')
    for component in components:
        if component in ('.', '..') or Path(component).anchor:
            raise ValueError('Unsafe backup member')
        path = path / component
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError('Unsafe backup member')
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('Invalid backup member')
    return path


def verify(folder, *, manifest=None):
    folder=Path(folder).resolve()
    if manifest is None:
        manifest=json.loads(bundle_file(folder,'manifest.json').read_text(encoding='utf-8'))
    database=bundle_file(folder,'momiq.sqlite3')
    if manifest.get('version')!=1 or digest(database)!=manifest.get('databaseSha256'):
        raise ValueError('Backup manifest/database mismatch')
    now=datetime.fromisoformat(manifest['created'])
    if now.tzinfo is None:raise ValueError('Backup manifest time has no zone')
    expected=references(database,now)
    if manifest.get('files')!=[{'path':path,'sha256':checksum} for path,checksum in expected]:
        raise ValueError('Backup media manifest mismatch')
    for relative,checksum in expected:
        source=bundle_file(folder,relative)
        if not source.resolve().is_relative_to(folder) or digest(source)!=checksum:
            raise ValueError('Backup video missing or corrupt')
    return {'database':'ok','mediaFiles':len(expected)}


def bundle_expiry(folder, *, manifest=None):
    """Existing 14-day DB backup rotation, shortened for earlier video expiry."""
    folder=Path(folder).resolve()
    if manifest is None:
        manifest=json.loads(bundle_file(folder,'manifest.json').read_text(encoding='utf-8'))
    created=datetime.fromisoformat(manifest['created'])
    if created.tzinfo is None:raise ValueError('Backup date requires timezone')
    expiry=created+timedelta(days=14)
    database=bundle_file(folder,'momiq.sqlite3')
    with closing(sqlite3.connect(f'{database.as_uri()}?mode=ro&immutable=1',uri=True)) as con:
        con.row_factory=sqlite3.Row
        ids={item['path'].split('/')[1] for item in manifest['files']}
        for identity in ids:
            row=con.execute('SELECT booking_id FROM booking_videos WHERE id=?',(identity,)).fetchone()
            if not row:raise ValueError('Backup media reference missing')
            video_expiry=expires_at(con,row['booking_id'])
            if video_expiry is not None:expiry=min(expiry,video_expiry)
    return expiry


def prune(root, now):
    """Only verified, generated bundles; never follow symlinks or recurse blindly."""
    root=Path(root).resolve()
    result={'removed':0,'failed':0}
    if not root.exists():return result
    with media_maintenance.lock(root):
        for folder in root.iterdir():
            if not re.fullmatch(r'\d{8}T\d{6}Z-[a-f0-9]{8}',folder.name):continue
            try:
                info=folder.lstat()
                if (not stat.S_ISDIR(info.st_mode) or getattr(info,'st_file_attributes',0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                        or folder.resolve().parent!=root):
                    raise ValueError('Unsafe backup path')
                if now<bundle_expiry(folder):continue
                verify(folder)
                manifest=json.loads(bundle_file(folder,'manifest.json').read_text(encoding='utf-8'))
                allowed={'manifest.json','momiq.sqlite3',*(item['path'] for item in manifest['files'])}
                # Older read-only SQLite verification could leave harmless sidecars.
                if (folder/'momiq.sqlite3-wal').exists():
                    if (folder/'momiq.sqlite3-wal').stat().st_size:raise ValueError('Unexpected WAL data')
                    allowed.add('momiq.sqlite3-wal')
                if (folder/'momiq.sqlite3-shm').exists():allowed.add('momiq.sqlite3-shm')
                directories={parent.as_posix() for relative in allowed for parent in Path(relative).parents if parent.as_posix()!='.'}
                files=[]
                checked_dirs=[folder]
                # Inspect each directory entry before descending. Unknown trees,
                # junctions, special files and hard links leave the bundle intact.
                for directory in checked_dirs:
                    for path in directory.iterdir():
                        info=path.lstat()
                        relative=path.relative_to(folder).as_posix()
                        if getattr(info,'st_file_attributes',0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                            raise ValueError('Unsafe backup content')
                        if stat.S_ISDIR(info.st_mode) and relative in directories:
                            checked_dirs.append(path)
                        elif stat.S_ISREG(info.st_mode) and info.st_nlink==1 and relative in allowed:
                            files.append(path)
                        else:
                            raise ValueError('Unexpected backup member')
                for path in files:path.unlink()
                for directory in reversed(checked_dirs):directory.rmdir()
                result['removed']+=1
            except (OSError,ValueError,TypeError,KeyError,IndexError,AttributeError,sqlite3.Error):
                result['failed']+=1
    return result


def create(data, target):
    with media_maintenance.lock(data):
        return _create(data,target)


def _create(data, target):
    data,target=Path(data).resolve(),Path(target).absolute()
    if target.exists() or target.is_symlink():raise ValueError('Backup destination already exists')
    target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with tempfile.TemporaryDirectory(prefix='.momiq-backup-',dir=target.parent) as temporary:
        staging=Path(temporary)/'bundle';staging.mkdir(mode=0o700)
        database=staging/'momiq.sqlite3'
        backup_database(bundle_file(data,'momiq.sqlite3'),database)
        database.chmod(0o600)
        now=datetime.now(timezone.utc)
        expected=references(database,now)
        for relative,checksum in expected:
            _, identity, name = relative.split('/')
            destination=staging/relative;destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            try:
                with video_media.open_derivative(data, identity, 'poster' if name == 'poster.jpg' else 'playback') as source, destination.open('xb') as output:
                    shutil.copyfileobj(source,output)
            except video_media.VideoUnavailable as error:
                raise ValueError('Unsafe or missing source video') from error
            destination.chmod(0o600)
            if digest(destination)!=checksum:raise ValueError('Source video missing or corrupt')
        manifest={'version':1,'created':now.isoformat(),
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
