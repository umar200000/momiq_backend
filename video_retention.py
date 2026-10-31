"""Approved: 30 days after termination and any dispute resolution; open hold."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import booking_engine as engine
import media_maintenance
from video_retention_policy import expires_at


def status(con, video, now):
    retirement=con.execute('SELECT expired_at FROM video_retirements WHERE video_id=?',(video['id'],)).fetchone()
    expiry=engine.parse(retirement['expired_at']) if retirement else expires_at(con,video['booking_id'])
    return {'available':not retirement and (expiry is None or now<expiry),
            'expiresAt':engine.stamp(expiry) if expiry else None}


def cleanup(con, root, now, limit=20):
    """Commit retirement first, then delete only canonical private derivatives.

Failures remain retryable. Never recursively delete unknown directory contents.
Run under the same lock as a backup snapshot/copy, so either operation sees a
complete referenced media set. Expired playback is denied even before this job.
"""
    if type(limit) is not int or not 1<=limit<=100:raise ValueError('Invalid cleanup limit')
    root=Path(root).resolve()
    result={'retired':0,'purged':0,'failed':0}
    with media_maintenance.lock(root):
        engine.begin(con)
        # Only terminal bookings can expire. A bounded retirement batch leaves
        # the immutable report metadata and audit trail in the database.
        cutoff=engine.stamp(now-timedelta(days=30))
        candidates=con.execute("SELECT v.id,v.booking_id FROM booking_videos v JOIN bookings b ON b.id=v.booking_id LEFT JOIN video_retirements r ON r.video_id=v.id LEFT JOIN booking_disputes d ON d.booking_id=b.id WHERE r.video_id IS NULL AND b.status IN ('completed','cancelled','rejected','expired') AND b.updated<=? AND (d.booking_id IS NULL OR (d.status='resolved' AND d.resolved_at<=?)) ORDER BY b.updated,v.id LIMIT ?",
            (cutoff,cutoff,limit)).fetchall()
        for video in candidates:
            expiry=expires_at(con,video['booking_id'])
            if expiry is None or now<expiry:continue
            con.execute('INSERT INTO video_retirements(video_id,expired_at) VALUES(?,?)',(video['id'],engine.stamp(expiry)))
            con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',
                ('system','video-expired',video['id'],engine.stamp(now)))
            result['retired']+=1
        con.commit()
        pending=con.execute('SELECT video_id FROM video_retirements WHERE purged_at IS NULL ORDER BY expired_at,video_id LIMIT ?',(limit,)).fetchall()
        for row in pending:
            identity=row['video_id']
            if not re.fullmatch(r'[a-f0-9]{32}',identity):raise ValueError('Invalid stored video ID')
            folder=root/'care-videos'/identity
            try:
                if folder.is_symlink() or not folder.resolve().is_relative_to(root/'care-videos'):
                    raise ValueError('Unsafe media folder')
                if folder.exists():
                    if any(p.name not in ('playback.mp4','poster.jpg') or p.is_symlink() or not p.is_file() for p in folder.iterdir()):
                        raise ValueError('Unexpected media files')
                    for name in ('playback.mp4','poster.jpg'):(folder/name).unlink(missing_ok=True)
                    folder.rmdir()
                engine.begin(con)
                con.execute('UPDATE video_retirements SET purged_at=? WHERE video_id=? AND purged_at IS NULL',(engine.stamp(now),identity))
                con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',('system','video-purged',identity,engine.stamp(now)))
                con.commit();result['purged']+=1
            except (OSError,ValueError):
                con.rollback();result['failed']+=1
    return result


if __name__=='__main__':
    import json
    import server
    with server.db() as con:result=cleanup(con,server.DATA,datetime.now(timezone.utc))
    print(json.dumps(result))
    if result['failed']:raise SystemExit(1)
