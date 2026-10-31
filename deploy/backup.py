#!/usr/bin/python3
"""Daily complete backup. Retention/offsite recovery remain release gates."""
from pathlib import Path
from datetime import datetime, timezone
import secrets
import sys

sys.path.insert(0,'/opt/momiq/current/backend')
from backup_bundle import create, prune

root=Path('/var/backups/momiq')
now=datetime.now(timezone.utc)
if sys.argv[1:] not in ([],['--prune-only']):raise SystemExit('Unsupported backup arguments')
if not sys.argv[1:]:
    target=root/(now.strftime('%Y%m%dT%H%M%SZ')+'-'+secrets.token_hex(4))
    print(create(Path('/var/lib/momiq'),target))
result=prune(root,now)
print(result)
if result['failed']:raise SystemExit(1)
