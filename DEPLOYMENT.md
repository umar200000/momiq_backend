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
