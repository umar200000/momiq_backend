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


def rehearse(bundle, mode):
    source = Path(bundle).resolve(strict=True)
    started = time.monotonic()
    backup_bundle.verify(source)
    manifest = json.loads(backup_bundle.bundle_file(source, 'manifest.json').read_text(encoding='utf-8'))
    created = datetime.fromisoformat(manifest['created'])
    now = datetime.now(timezone.utc)
    if now >= backup_bundle.bundle_expiry(source):
        raise ValueError('Backup retention elapsed')
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
            wallets = con.execute('SELECT COUNT(*) FROM wallet_accounts').fetchone()[0]
            entries = con.execute('SELECT COUNT(*) FROM wallet_entries').fetchone()[0]
    return {'schema':schema, 'mediaFiles':result['mediaFiles'], 'walletAccounts':wallets,
            'journalEntries':entries, 'reconciled':True,
            'snapshotAgeSeconds':round((now-created).total_seconds(), 2),
            'drillSeconds':round(time.monotonic()-started, 3)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--mode', choices=('local','test','staging','production'), required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(rehearse(args.bundle, args.mode)))
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        parser.exit(1, 'Offline restore verification failed\n')
