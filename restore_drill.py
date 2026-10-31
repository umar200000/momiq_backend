"""Rehearse a verified bundle restore in a disposable offline directory."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
from tempfile import TemporaryDirectory
import time

import backup_bundle
import deployment_health
import migrations
from predeploy_backup import known_schema


def rehearse(bundle, mode):
    source = Path(bundle).resolve(strict=True)
    started = time.monotonic()
    backup_bundle.verify(source)
    manifest = json.loads(backup_bundle.bundle_file(source, 'manifest.json').read_text(encoding='utf-8'))
    created = datetime.fromisoformat(manifest['created'])
    now = datetime.now(timezone.utc)
    if now < created or now >= backup_bundle.bundle_expiry(source):
        raise ValueError('Backup snapshot is future-dated or its retention elapsed')
    with TemporaryDirectory(prefix='momiq-offline-restore-') as tmp:
        restored = Path(tmp).resolve()
        # Derive media members from the restored database, not manifest path strings.
        def copy_member(relative):
            target = restored / relative
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with backup_bundle.bundle_file(source, relative).open('rb') as src, target.open('xb') as dst:
                os.chmod(target, 0o600)
                shutil.copyfileobj(src, dst)
        copy_member('momiq.sqlite3')
        copy_member('manifest.json')
        for relative, _ in backup_bundle.references(restored/'momiq.sqlite3', created):
            copy_member(relative)
        result = backup_bundle.verify(restored)
        with closing(sqlite3.connect(restored/'momiq.sqlite3')) as con:
            before = known_schema(con,mode)
            con.execute('PRAGMA foreign_keys=ON')
            applied = migrations.migrate(con)
        if applied:
            expected = [(item['path'],item['sha256']) for item in manifest['files']]
            if backup_bundle.references(restored/'momiq.sqlite3',created) != expected:
                raise ValueError('Migrated restore has different media references')
        schema = deployment_health.check_database(restored, mode)
        uri = (restored/'momiq.sqlite3').as_uri() + '?mode=ro'
        with closing(sqlite3.connect(uri, uri=True)) as con:
            con.execute('PRAGMA query_only=ON')
            mismatch = con.execute("""
                SELECT 1 FROM wallet_accounts w LEFT JOIN wallet_entries e ON w.user_id=e.user_id
                GROUP BY w.user_id,w.balance_minor
                HAVING COALESCE(SUM(e.amount_minor),0)<>w.balance_minor LIMIT 1""").fetchone()
            if mismatch:
                raise ValueError('Restored wallet journal mismatch')
            if con.execute("""
                SELECT 1 FROM (
                    SELECT balance_after, SUM(amount_minor) OVER (
                        PARTITION BY user_id ORDER BY rowid ROWS UNBOUNDED PRECEDING
                    ) running FROM wallet_entries
                ) WHERE balance_after<>running LIMIT 1""").fetchone():
                raise ValueError('Restored wallet running balance mismatch')
            if con.execute("""
                SELECT 1 FROM topup_requests t LEFT JOIN wallet_entries e ON e.source_key='topup:'||t.id
                WHERE (t.status='approved' AND (e.id IS NULL OR e.kind<>'topup' OR
                       e.user_id<>t.user_id OR e.amount_minor<>t.amount_minor OR e.actor IS NOT t.reviewed_by))
                   OR (t.status<>'approved' AND e.id IS NOT NULL)
                UNION ALL SELECT 1 FROM wallet_entries e
                WHERE e.source_key GLOB 'topup:*'
                  AND NOT EXISTS(SELECT 1 FROM topup_requests t WHERE t.id=substr(e.source_key,7))
                LIMIT 1""").fetchone():
                raise ValueError('Restored top-up decision and credit disagree')
            if con.execute("""
                SELECT 1 FROM wallet_corrections c JOIN wallet_entries debit ON debit.id=c.entry_id
                JOIN wallet_entries credit ON credit.id=c.original_entry_id
                JOIN topup_requests t ON t.id=c.topup_id
                WHERE credit.source_key<>'topup:'||t.id OR debit.source_key<>'topup-correction:'||c.id
                   OR debit.kind<>'topup_correction' OR debit.amount_minor<>-c.amount_minor
                   OR c.user_id<>t.user_id OR debit.user_id<>t.user_id OR debit.actor<>c.actor
                   OR debit.reason<>c.reason
                UNION ALL SELECT 1 FROM wallet_entries e
                WHERE (e.kind='topup_correction' OR e.source_key GLOB 'topup-correction:*')
                  AND NOT EXISTS(SELECT 1 FROM wallet_corrections c WHERE c.entry_id=e.id)
                LIMIT 1""").fetchone():
                raise ValueError('Restored top-up correction and debit disagree')
            if con.execute("""
                SELECT 1 FROM (
                    SELECT c.expected_minor,c.amount_minor,t.amount_minor original,
                           SUM(c.amount_minor) OVER (PARTITION BY c.topup_id ORDER BY debit.rowid
                               ROWS UNBOUNDED PRECEDING) total
                    FROM wallet_corrections c JOIN wallet_entries debit ON debit.id=c.entry_id
                    JOIN topup_requests t ON t.id=c.topup_id
                ) WHERE expected_minor<>total-amount_minor OR total>original LIMIT 1""").fetchone():
                raise ValueError('Restored correction exceeds or skips the original credit')
            if con.execute("""
                SELECT 1 FROM booking_disputes d JOIN bookings b ON b.id=d.booking_id
                JOIN booking_quotes q ON q.id=b.quote_id
                WHERE d.status='resolved' AND (
                    d.refund_minor>json_extract(q.snapshot,'$.price.commission_minor')
                    OR (d.outcome='continue' AND d.refund_minor<>0)
                    OR (d.outcome='not_started' AND d.refund_minor<>json_extract(q.snapshot,'$.price.commission_minor'))
                ) LIMIT 1""").fetchone():
                raise ValueError('Restored dispute refund contradicts its decision')
            if con.execute("""
                WITH agreements AS (
                    SELECT b.id,b.sitter_id,json_extract(q.snapshot,'$.price.commission_minor') fee
                    FROM bookings b JOIN booking_quotes q ON q.id=b.quote_id
                    WHERE EXISTS(SELECT 1 FROM booking_events e WHERE e.booking_id=b.id AND e.action='accept')
                ), expected(source_key,user_id,amount_minor,kind,actor) AS (
                    SELECT 'booking:'||id||':commission',sitter_id,-fee,'commission',sitter_id
                    FROM agreements WHERE fee>0
                    UNION ALL
                    SELECT 'booking:'||a.id||':refund',a.sitter_id,a.fee,'commission_refund',e.actor
                    FROM agreements a JOIN booking_events e ON e.booking_id=a.id
                    WHERE e.action='cancel' AND a.fee>0
                    UNION ALL
                    SELECT 'booking:'||a.id||':refund',a.sitter_id,d.refund_minor,'commission_refund',e.actor
                    FROM agreements a JOIN booking_disputes d ON d.booking_id=a.id
                    JOIN booking_events e ON e.booking_id=a.id AND e.action='resolve_dispute'
                    WHERE d.status='resolved' AND d.refund_minor>0
                ), actual AS (
                    SELECT source_key,user_id,amount_minor,kind,actor FROM wallet_entries
                    WHERE kind IN ('commission','commission_refund') OR source_key GLOB 'booking:*'
                )
                SELECT * FROM (SELECT * FROM expected EXCEPT SELECT * FROM actual)
                UNION ALL SELECT * FROM (SELECT * FROM actual EXCEPT SELECT * FROM expected)
                LIMIT 1""").fetchone():
                raise ValueError('Restored booking commission disagrees with the agreement or refund decision')
            wallets = con.execute('SELECT COUNT(*) FROM wallet_accounts').fetchone()[0]
            entries = con.execute('SELECT COUNT(*) FROM wallet_entries').fetchone()[0]
        # A snapshot can predate a logout or an operator revocation. Rehearse
        # invalidating both credential types only on the isolated recovery copy.
        with closing(sqlite3.connect(restored/'momiq.sqlite3')) as recovered, recovered:
            recovered.execute('BEGIN IMMEDIATE')
            sessions=dict(recovered.execute('SELECT role,COUNT(*) FROM sessions GROUP BY role'))
            removed=recovered.execute('DELETE FROM sessions').rowcount
            if removed!=sum(sessions.values()) or recovered.execute('SELECT 1 FROM sessions LIMIT 1').fetchone():
                raise ValueError('Restored session invalidation failed')
            if removed:
                recovered.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',
                                  ('offline-recovery','recovery-session-reset',json.dumps({'removed':removed}),now.isoformat()))
    return {'schema':schema, 'schemaBefore':before, 'migrationsApplied':applied,
            'mediaFiles':result['mediaFiles'], 'walletAccounts':wallets,
            'journalEntries':entries, 'reconciled':True,
            'restoredSessionsRevoked':removed,
            'snapshotAgeSeconds':(now-created).total_seconds(),
            'drillSeconds':time.monotonic()-started}


def recovery_status(result, max_snapshot_age_seconds, max_drill_seconds):
    limits={'snapshotAgeSeconds':max_snapshot_age_seconds,'drillSeconds':max_drill_seconds}
    breached=[]
    for metric,limit in limits.items():
        if limit is None:continue
        if limit<0:raise ValueError('Recovery limit must be non-negative')
        if result[metric]>limit:breached.append(metric)
    return {'breached':breached,'limits':{k:v for k,v in limits.items() if v is not None}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--mode', choices=('local','test','staging','production'), required=True)
    parser.add_argument('--max-snapshot-age-seconds',type=int)
    parser.add_argument('--max-drill-seconds',type=int)
    args = parser.parse_args()
    try:
        result=rehearse(args.bundle, args.mode)
        status=recovery_status(result,args.max_snapshot_age_seconds,args.max_drill_seconds)
        print(json.dumps({**result,**status}))
        if status['breached']:raise SystemExit(2)
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        parser.exit(1, 'Offline restore verification failed\n')
