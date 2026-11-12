"""Read local disk, host RAM, SQLite size and pending queue counts without private rows."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import sqlite3
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import deployment_health


def available_ram():
    try:
        contents=Path('/proc/meminfo').read_text(encoding='ascii')
    except FileNotFoundError:
        return None
    match=re.search(r'^MemAvailable:\s+(\d+) kB$',contents,re.M)
    return int(match[1])*1024 if match else None


def snapshot(data,mode):
    data=Path(data).resolve(strict=True)
    schema=deployment_health.check_database(data,mode)
    database=data/'momiq.sqlite3'
    with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True,timeout=2)) as con:
        con.execute('BEGIN')
        if con.execute("SELECT value FROM runtime_metadata WHERE key='environment'").fetchone()!=(mode,):
            raise ValueError('Instance changed')
        topups=con.execute("SELECT COUNT(*) FROM topup_requests WHERE status='pending'").fetchone()[0]
        support=con.execute("SELECT COUNT(*) FROM support_tickets WHERE status='open'").fetchone()[0]
        now = datetime.now(timezone.utc).isoformat(timespec='microseconds')
        expired_requests = con.execute(
            "SELECT COUNT(*) FROM bookings WHERE status='pending' AND reply_deadline<=?", (now,)
        ).fetchone()[0]
        overdue_disputes = con.execute(
            "SELECT COUNT(*) FROM booking_disputes WHERE status='open' AND deadline<=?", (now,)
        ).fetchone()[0]
        # Logical Base64 bytes include the current receipt and immutable evidence
        # claim copies. These are already inside databaseBytes, not extra files.
        receipts = con.execute('SELECT COALESCE(SUM(length(CAST(receipt AS BLOB))),0) FROM topup_requests').fetchone()[0]
        evidence = con.execute('SELECT COALESCE(SUM(length(CAST(receipt AS BLOB))),0) FROM topup_evidence_claims').fetchone()[0]
        videos = con.execute('''SELECT COUNT(*),COALESCE(SUM(v.bytes),0)
            FROM booking_videos v LEFT JOIN video_retirements r ON r.video_id=v.id
            WHERE r.purged_at IS NULL''').fetchone()
        pending_purge = con.execute('SELECT COUNT(*) FROM video_retirements WHERE purged_at IS NULL').fetchone()[0]
        try:
            wal=(data/'momiq.sqlite3-wal').stat().st_size
        except FileNotFoundError:
            wal=0
    return {'schema':schema,'diskFreeBytes':shutil.disk_usage(data).free,'databaseBytes':database.stat().st_size,
            'hostAvailableRamBytes':available_ram(),'walBytes':wal,'pendingTopups':topups,'openSupport':support,
            'expiredPendingBookings':expired_requests,'overdueOpenDisputes':overdue_disputes,
            'currentReceiptBase64Bytes':receipts,'evidenceReceiptBase64Bytes':evidence,
            'receiptStoredBase64Bytes':receipts+evidence,
            'unpurgedVideoCount':videos[0],'unpurgedVideoRecordedBytes':videos[1],
            'pendingVideoPurgeCount':pending_purge}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',required=True)
    parser.add_argument('--mode',required=True,choices=('local','test','staging','production'))
    thresholds={'min-disk-free-bytes':'diskFreeBytes','min-host-available-ram-bytes':'hostAvailableRamBytes',
                'max-wal-bytes':'walBytes','max-pending-topups':'pendingTopups','max-open-support':'openSupport',
                'max-expired-pending-bookings':'expiredPendingBookings','max-overdue-open-disputes':'overdueOpenDisputes',
                'max-receipt-stored-base64-bytes':'receiptStoredBase64Bytes',
                'max-unpurged-video-recorded-bytes':'unpurgedVideoRecordedBytes',
                'max-pending-video-purge-count':'pendingVideoPurgeCount'}
    for flag in thresholds:
        parser.add_argument('--'+flag,type=int)
    args=parser.parse_args(argv)
    try:
        metrics=snapshot(args.data,args.mode)
        breached,missing=[],[]
        for flag,metric in thresholds.items():
            limit=getattr(args,flag.replace('-','_'))
            if limit is None:
                continue
            if limit<0:
                raise ValueError('Invalid limit')
            value=metrics[metric]
            if value is None:
                missing.append(metric)
            elif (value < limit if flag.startswith('min-') else value > limit):
                breached.append(metric)
        print(json.dumps({'metrics':metrics,'breached':breached,'unavailable':missing}))
        return 2 if missing else int(bool(breached))
    except (ValueError,OSError,sqlite3.Error):
        print('Instance metrics unavailable',file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
