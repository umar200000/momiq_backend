#!/usr/bin/python3
"""Daily complete backup. Retention/offsite recovery remain release gates."""
from pathlib import Path
from datetime import datetime, timezone
import secrets
import sys

sys.path.insert(0,'/opt/momiq/current/backend')
from backup_bundle import create

root=Path('/var/backups/momiq')
target=root/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+secrets.token_hex(4))
print(create(Path('/var/lib/momiq'),target))
