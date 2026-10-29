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

Flutter CI checks analysis/tests, Android builds and an unsigned iOS simulator build. Local/test booking, sitter and wallet workflows are implemented; hosted booking/publication remain deliberately gated. Mobile store publication, signing, SMS, MyID, external pushes and real-device acceptance remain separate release work. The checklist records exact tested commits and remaining gates.

## Empty catalog and removal of demo data

`GET /api/sitters` reads the paginated moderated service catalog. There is no automatic demo seed; explicitly seeded local TEST listings are not production-approved/MyID-verified listings. The legacy `sitters` table is retained for old support/favorite records, not as the current catalog source. Account enrollment, listing submission and test moderation exist; production verification/publication are still gated.

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

## Administrator session revocation

Schema 23 removes orphaned administrator sessions during upgrade. Subsequent deletion, renaming, password/salt changes or replacement of an administrator record revoke that operator's sessions atomically. Recreating the same username never revives its old cookies; ordinary client sessions are unaffected. Every authenticated admin request also requires a current administrator record. Credential verification and session issuance share a write transaction so a concurrent password reset cannot leave a newly issued old-password session behind.

This protects subsequent authentication, not cancellation of a request already authorized and in flight. These changes require schema 23 or later; migrate with a verified backup and never roll back only the code against a newer schema.

## Individual operators and least privilege (schema 24)

| Role | Allowed work | Restricted work |
| --- | --- | --- |
| `support` | Private support ticket list, replies, resolution and attached evidence | Accounts, wallet, bookings, disputes and settings |
| `moderation` | Listings and their moderation; reported chat evidence and review moderation | Full private account profiles, wallet, support, bookings and settings |
| `finance` | Top-up queue, private receipts/history, verified credit decisions, source-linked corrections and financial aggregates | Profiles, chat, care, disputes and commission/QR configuration |
| `administrator` | Existing full administration, commission/QR and dispute decisions | Cannot edit/delete immutable audit or financial history through the API |

The server enforces exact method/path allowlists before calling the endpoint; new routes are denied to limited roles until deliberately assigned. `GET /api/admin/me` returns the authenticated username, role and available panels. The panel loads that identity before private indexes and clears old views on session expiry; hiding a menu is not the permission enforcement. There are no wildcard limited-role privileges or implicit grants from request JSON. Permission changes/disable/delete invalidate all existing operator sessions. Freshly inserted administrator rows without an explicit permission grant cannot log in.

Migration 24 preserves existing administrator privileges once. Fresh database bootstrap creates one administrator with generated/local configured credentials; an existing database with all operators deleted does **not** silently recreate a shared administrator. Provision named operators from the trusted server console, using the existing data-directory environment and runtime:

```sh
# MOMIQ_DATA_DIR must already point to the intended, backed-up and migrated DB.
python manage_operators.py support.one --actor admin --role support --reset-password --reason "Named support operator approved for ticket handling"
python manage_operators.py support.one --actor admin --role support --disable --reason "Operator access withdrawn after departure"
```

The command prompts privately for the current administrator password and, when requested, the new operator password twice. Never pass passwords as shell arguments, environment variables or audit reasons. Choose a unique 14–200 character password per operator and deliver it privately. Only an enabled administrator with a valid password can provision; the last enabled administrator cannot be disabled/demoted through this tool. Role changes and password resets append a before/after/reason audit without passwords, salts or hashes, in the same transaction. An audit-write failure rolls back provisioning. A no-op does not invalidate sessions or invent an audit event.

MFA, password-change self-service, emergency recovery, individual-operator native acceptance and production rollout remain release gates. Do not enable public operational access based solely on password plus role separation. Existing in-flight authorization and all end-to-end access boundaries still require the M102 review.

## Reproducible isolated load investigation

The approved first scale is 1,000 synthetic accounts and 100 simultaneously active customers. Run `python tool/load_test.py --accounts 1000 --active 100 --cycles 5 --output <new-report.json>`. The command creates its own temporary database and loopback server; there is no existing-server URL/database option. It seeds 100 TEST sitters with all three services, 900 TEST customers and local sessions, then exercises discovery, profile, booking history, inbox, notices and chat writes. Temporary data is removed after the report; credentials and private response bodies are not included. CI runs the 20-account/two-customer fixture smoke only, not a production benchmark. For a paced local run use `python tool/load_test.py --accounts 1000 --active 100 --duration-seconds 120 --think-ms 1000 --output <new-report.json>`. Duration mode replaces fixed cycles, checks its deadline before each request, and waits the specified think time after each response. In-flight requests may drain after the duration; elapsed/throughput include HTTP shutdown. Duration is bounded to 1–300 seconds and think time to 100–10000 ms. Its expectedRequests is null because the count depends on response time, while successfulRequests must equal all attempted requests. A two-minute paced run is still not an extended soak or proof of hosted capacity. Automated smoke tests additionally verify both modes cannot touch a pre-existing configured data directory and cannot overwrite evidence.

On the 2026-10-29 Windows development machine, the initial synchronized burst completed 3,498/3,500 requests, with two connection failures and booking-history p95 8.72 seconds. Empty booking-expiry checks unnecessarily queued for a SQLite write lock; they now first read for due work and recheck under the write lock before any transition. Single-listing chat/quote/review lookups now query the intended sitter/service using the same eligibility checks, instead of constructing the whole catalog under the chat transaction. The local HTTP listen backlog was five and produced observed connection-refused errors; the real local launcher and the harness now both use 128. Gunicorn/Nginx are separate hosted transports.

After these changes, the same 3,500-request burst completed without HTTP/transport errors in 15.13 seconds. The database retained exactly 1,000 accounts, 100 conversations and 500 messages; integrity and foreign keys passed, with no bookings or financial actions. Booking-history p95 was 220 ms. However, catalog p95 remained 3.67 seconds, chat-open p95 5.71 seconds and chat-send p95 2.32 seconds. These residual tail latencies remain open performance findings; success status does not mean the latency target has been met. This workload has synchronized starts and no user think time, empty booking histories, no TLS/mobile network/video/SMS and no production host. Extended soak, larger populated histories, media contention, hosted load and agreed latency/availability/RPO/RTO criteria are still required before choosing SQLite versus PostgreSQL or claiming production capacity. Raw local reports are referenced in the checklist.

A later 120-second paced local run (100 active customers, 1,000 accounts, 1,000 ms think time after each response) completed 11,635/11,635 requests in 120.49 seconds, with catalog p95 2,258 ms. Joining approved moderation metadata into the main discovery query removed one per-listing round trip without relaxing fingerprint/balance/privacy checks. The repeated paced run completed 11,705/11,705 requests in 120.51 seconds (97.13 requests/s); catalog p95 2,127 ms, profile 19 ms, booking history 20 ms, inbox 18 ms, notices 19 ms, chat open 26 ms and chat send 55 ms. Both preserved DB integrity/FKs, 1,000 accounts, 100 conversations, 1,600 synthetic messages and zero bookings. The accompanying burst completed 3,500/3,500 in 11.21 seconds. These are individual runs on a shared development machine: the small timing differences are observations, not a statistically established speedup. Catalog burst/tail latency is still a finding. None of these tests exercise production-host configuration, long booking histories, TLS, video or an extended soak.


A subsequent read-only fast path for reopening existing chats keeps the new-contact write-lock recheck, and discovery skips unselected services before projection. Its same local burst completed 3,500/3,500 in 11.71 seconds (catalog p95 2.43s, booking-history 212ms, chat-open 5.01s, chat-send 1.31s). This improves measured work without closing the residual latency/hosted acceptance findings above. The full 249-test Python suite passed after these changes.


## Aggregate operational reports

`GET /api/admin/metrics` and `/api/admin/metrics.csv` require a current operator session. Finance receives wallet journal totals, total sitter balances, top-up request status counts and oldest pending receipt age only. Administrators additionally receive booking/support/dispute status counts, overdue dispute counts, oldest open support ticket age and mean time from ticket creation to the first support-authored message. The mean includes replied tickets only; empty queues/unanswered samples have a null duration, not an invented zero. Ages use UTC creation timestamps, including legacy date-only values treated as UTC. This is not a configured SLA or a guarantee that overdue work has been handled.

Reports reject arbitrary filters and row-level selectors. CSV contains fixed metric names, exact integer minor units/counts/durations and the snapshot UTC time; no user IDs, names, phones, addresses, evidence, references or message bodies are exported. Money is serialized as integer strings and rendered using BigInt to avoid JavaScript precision loss. CSV refreshes its snapshot at download time. Both JSON access and CSV export append the authenticated operator and report scope to immutable audit. Responses are no-store; the CSV uses a fixed attachment filename and nosniff.

Journal credit/commission/refund/correction totals and balances are operational accounting data, not a tax statement, platform profit calculation, proof of bank receipt or customer service payment report. Rejected/needs-info counts describe receipt review requests, not failed bank transfers. Fiscal interpretation and mandatory receipt requirements remain M066. MFA, hosted rollout and final native acceptance remain separate release gates.


### Catalog measurement correction and optimization, 2026-10-29

Version 1 of the isolated load tool included urllib's first concurrent lazy opener/ambient proxy initialization in client latency. Instrumentation separated a roughly 2.3-second initial client p95 from roughly 191 ms in the catalog calculation, so those earlier client figures are not database-only latency. Version 2 builds an independent direct loopback opener per customer before timing, without HTTP warmup, and separately reports initial/repeated cycles and application-handler duration. No production HTTP handler or proxy configuration is changed by this instrumentation.

The catalog query now reads directly in listing_moderation's composite primary-key order with a tuple cursor, avoiding a temporary ORDER BY sort and scanning the user table as the driver. Visible, non-TEST review totals are computed in the same SQL snapshot instead of one additional Python/SQLite call per returned listing. Current publication fingerprint, blocked state, minimum balance, service, date availability and review-visibility rules remain checked; no response cache was introduced.

With the SAME version-2 harness and 1,000 accounts/100 customers/120 seconds/1,000 ms think time, baseline commit4ace241 completed11,858/11,858 requests and the update11,899/11,899. Catalog client p95 changed239.15→110.97ms; handler p95 changed130.02→57.93ms. Repeat-cycle client p95 changed23.84→21.05ms; initial-cycle client p95 changed520.21→460.78ms. The updated3,500-request burst also passed; first chat creation still has write-contention tails. See performance/catalog-2026-10-29.json for sanitized complete reports and source hashes. These are single paired observations on a shared workstation, not statistically established bounds, production capacity or proof of hosted latency. Extended soak, larger populated histories/media and the hosted transport remain release checks.

Deploy the paired admin panel with the reason-required profile/block/legacy-redaction API. Old forms receive400 and must reload; there is no fallback that invents an audit reason. No schema migration is added by these changes; schema25 and previous audit history remain intact.
