# Hosted test environment

- API: https://api.momiq.net/api/health
- Admin: https://admin.momiq.net
- Root: https://momiq.net redirects to admin.
- Server: Ubuntu 24.04, 95.182.119.218.

## Automatic delivery

Push to `main` in `umar200000/momiq_backend` or `umar200000/momiq_admin`: GitHub Actions tests the commit, connects using a separate restricted key, and deploys the exact SHA. PRs only run tests. Server accepts only the current main SHA, serializes deployments with flock, and restores the previous backend release if its health check fails. Admin updates are picked up without restarting the backend. Runtime data is outside release directories.

Secrets per repository: `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS`. Keys cannot open an interactive shell or forward ports. Server allows each key to deploy only its own component. Workflow Actions are pinned to commit hashes. Changes to bootstrap/systemd/nginx scripts require a deliberate server configuration update; normal deployment does not install them automatically.

## Server layout

- `/opt/momiq/current/backend`, `/opt/momiq/current/admin`: active release symlinks.
- `/opt/momiq/releases/`: previous releases retained for manual recovery.
- `/var/lib/momiq/`: SQLite and initial `admin-login.txt`; accessible to the service user/root only.
- `/etc/momiq/backend.env`: runtime settings, mode 600.
- `momiq.service`: Gunicorn on 127.0.0.1:8080, behind Nginx.
- `/etc/nginx/sites-available/momiq`: domains and HTTPS routing.

## Temporary authentication

By explicit owner request, `MOMIQ_ALLOW_TEST_LOGIN=1` enables the shared code `111111` even with HTTPS. ANY person knowing a phone number can sign in as that account. Use only test accounts/data. This is not a production-ready customer launch. Set the flag to `0` and restart `momiq` to close client sign-in until an SMS provider is implemented. Local development keeps its existing test login. No local users, chats or credentials are migrated to the server.

## Operations

```sh
sudo systemctl status momiq nginx
sudo journalctl -u momiq -n 100 --no-pager
sudo systemctl restart momiq
sudo certbot certificates
sudo certbot renew --dry-run
sudo systemctl list-timers certbot.timer momiq-backup.timer
sudo systemctl start momiq-backup.service
```

Certbot handles all three hostnames and automatic renewal; renewal hook tests/reloads Nginx. Certificates are requested without account email; monitor renewal via the timer logs and certificate expiry checks.

Daily SQLite backups use the backup API (WAL-safe), run integrity_check, and retain 14 days in `/var/backups/momiq`. They are ON THE SAME SERVER, not disaster recovery/offsite backups. Configure a separate storage destination before real use. Releases are currently retained; monitor disk usage.

## Rollback

Select an existing release directory under `/opt/momiq/releases/backend`, replace the active backend symlink atomically and restart `momiq`, then verify `/api/health`. Never restore a database snapshot blindly over newer data. Schema migrations need separate compatibility/backup planning.

## Mobile app

Flutter CI checks analysis/tests. App API default is the hosted HTTPS endpoint. Mobile store publication, signing, SMS, pushes, bookings and sitter-side backend completion are separate work.

## Empty catalog and removal of demo data

`GET /api/sitters` reads active rows from SQLite `sitters`; the table is created empty. There is no automatic demo seed. Real sitter registration/publication is not implemented by this change. Admin chat is unavailable until real sitter records exist.

One-time migration: `sudo python3 /opt/momiq/current/backend/deploy/cleanup_demo_data.py /var/lib/momiq/momiq.sqlite3 /var/backups/momiq`. It first creates a verified backup, removes messages/favorites for the five former hardcoded demo contacts and removes the known deployment test account only when its phone and profile match. Other accounts and uploaded pets/addresses are retained. The command is idempotent and not part of normal deployments.


## Access-log privacy

The local HTTP transport records only a whitelisted method, coarse route group and response code. Raw paths, query strings, client IPs, cookies, headers and malformed request lines are not printed. This prevents proximity coordinates and admin phone/name searches appearing in ordinary access logs.

Gunicorn explicitly loads `gunicorn.conf.py`; its access format contains response status, bytes and elapsed seconds only. Each Momiq Nginx virtual host overrides inherited combined access logging with a timestamp/status/bytes/duration format. Bootstrap preserves any existing `momiq-access.log` content and sets root:adm 0640; standard host log rotation/retention still needs operational verification. Applying these service/site changes requires privileged bootstrap/systemd reload/Nginx validation; a branch push alone does not install them.

These changes do not erase old logs, and do not claim to sanitize every Nginx/Gunicorn error log or external monitoring collector. Error-log access/retention, historical personal data and host-wide configuration remain M108/M113/M116 release work. Preserve useful diagnostics under restricted access rather than disabling error monitoring.

Format references: [Gunicorn logging settings](https://gunicorn.org/reference/settings/#access-log-format) and [Nginx log module](https://nginx.org/en/docs/http/ngx_http_log_module.html).

## Runtime dependency integrity and advisory checks

`requirements.txt` includes `requirements.lock`: the complete three-package Python runtime with exact versions and SHA-256 hashes of non-yanked release distributions from PyPI. Setup, CI and deployment use pip `--require-hashes --only-binary=:all:`; an unsupported platform fails instead of pulling unpinned source-build dependencies. Runtime versions have not changed. To update a dependency, resolve the complete runtime, deliberately refresh version/release hashes, run full tests and review the platform-specific artifact selection; never remove hashes to bypass an install failure.

CI runs pip-audit 2.10.1 in a separate tooling virtual environment with `--disable-pip --require-hashes -r requirements.txt`; a known advisory or failed audit prevents the test job, and therefore deployment, from passing. The local 2026-10-29 scan reported no known advisories for gunicorn23.0.0, packaging25.0 and Pillow13.0.0. This covers the published Python package advisory feed, not proof against unknown vulnerabilities, native codec/OS vulnerabilities, malicious packages, the audit tool's own dependency chain, secrets or licensing. Git/history secret scanning, credential rotation and the remaining native/mobile inventory remain M107/M131 work. [pip-audit documentation](https://pypi.org/project/pip-audit/).

All three repositories additionally fetch full Git history and run checksum-pinned [Gitleaks 8.30.1](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1), with upstream default rules, no ignored fingerprints/inline allow comments and 100% output redaction. The scan is local to the runner and fails the test job on findings/errors; app/secret contents are not uploaded to a scanner service. Local scans of 70 backend, 62 app and 26 admin commits across currently reachable local refs reported no detected secrets. This does not include unreachable/deleted remote history, private untracked runtime files, old logs or provider-side restrictions/rotation. A clean pattern scan is not proof that no secret exists.
