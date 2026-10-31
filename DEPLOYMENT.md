# Hosted test environment

- API: https://api.momiq.net/api/health
- Admin: https://admin.momiq.net
- Root: https://momiq.net redirects to admin.
- Server: Ubuntu 24.04, 95.182.119.218.

## Automatic delivery

The delivery workflow targets pushes to `main` in `umar200000/momiq_backend` or `umar200000/momiq_admin`: GitHub Actions tests the commit and requests deployment of the exact SHA using a separate restricted key. PRs only run tests. The deploy source accepts only the current main SHA and serializes deployments with flock. Its new smoke and rollback guards described below require installation by a privileged operator; a draft-branch push does not install this script or update production. Admin assets are picked up without restarting the backend. Runtime data is outside release directories.

Secrets per repository: `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS`. Keys cannot open an interactive shell or forward ports. Server allows each key to deploy only its own component. Workflow Actions are pinned to commit hashes. Changes to bootstrap/systemd/nginx scripts require a deliberate server configuration update; normal deployment does not install them automatically.

## Server layout

- `/opt/momiq/current/backend`, `/opt/momiq/current/admin`: active release symlinks.
- `/opt/momiq/releases/`: previous releases retained for manual recovery.
- `/var/lib/momiq/`: SQLite and initial `admin-login.txt`; accessible to the service user/root only.
- `/etc/momiq/backend.env`: runtime settings, mode 600.
- `momiq.service`: Gunicorn on 127.0.0.1:8080, behind Nginx.
- `/etc/nginx/sites-available/momiq`: domains and HTTPS routing.

## Temporary authentication

The older hosted test setup used `MOMIQ_ALLOW_TEST_LOGIN=1` with HTTPS. This is a known transition blocker, not the configuration accepted by the new production code: `MOMIQ_ENV=production` plus that flag fails at startup. The shared `111111` code allows signing in using only a phone number and must remain confined to isolated TEST data. A privileged operator must reconcile the hosted environment and set test login to `0` before promotion; client login remains unavailable until SMS integration. The release smoke also rejects test login in staging when assessing a candidate for promotion, even though isolated staging configuration can explicitly enable it. Local development retains its test login. No local users, chats or credentials are migrated to the server.

## Operations

Incident triage, money/retry handling, backup/recovery boundaries and responsibility/cost gaps are documented in [OPERATIONS.md](OPERATIONS.md). This is a source-grounded runbook, not proof of installed monitoring or hosted acceptance.

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

Before selecting old code, run that release's `deployment_health.py --data <runtime-data-directory> --mode <runtime-mode>` with its own Python runtime. It must confirm the current database environment and exact migration checksums without writing. A missing checker, older/newer schema or failed read blocks automatic code rollback. A passing schema check is necessary but does not prove every business/data compatibility property; operator recovery and migration/backup planning remain required. Never restore a database snapshot blindly over newer data. After any approved switch/restart, repeat the full release smoke, not only `/api/health`.

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
| `support` | Private support ticket list, replies, ordinary-ticket resolution and attached evidence; appeal closure is administrator-only | Accounts, wallet, bookings, disputes and settings |
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

MFA, password-change self-service, emergency recovery, individual-operator native acceptance and production rollout remain release gates. Do not enable public operational access based solely on password plus role separation. Request transaction authorization now rechecks revoked/expired credentials and operator permissions after writer-lock acquisition; complete hosted/native access boundaries still require the M102 review.

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


### Paired admin contract and immutable CI fixture

`admin-release.json` records the exact `umar200000/momiq_admin` commit and contract version tested with this backend. CI validates its strict schema, checks out that full commit SHA, and checks the checkout identity plus all required admin assets before running tests. Updating the admin pin is a reviewed code change; CI no longer silently follows the other repository's moving default branch. Contract 1 includes the role-aware sections, work queue, metrics and reason-required legacy mutations.

`python release_pair.py --backend <backend-release> --admin <admin-release> --actual-admin-revision <sha>` validates both the declared contract/assets and the exact CI pin. Without the optional revision argument it validates runtime compatibility, allowing a separately tested newer panel that preserves the same contract. This distinction is intentional: a declared contract is not proof of every newer panel's behavior. The admin's own tests and release acceptance remain required. Missing manifests, unsupported versions, duplicate/unknown keys, invalid pins, missing/empty assets and assets escaping their release directory fail closed.

The updated `momiq-deploy` validates a candidate backend against the current admin before database setup, and a candidate admin against the current backend before changing its symlink. Existing latest-main SHA and deploy-lock checks still apply. **The initial contract-aware pair cannot be bootstrapped by independently pushing one incompatible half.** A trusted operator must stage the compatible pair during the existing controlled initial rollout, with verified backups and maintenance; no mismatch bypass is provided. Atomic pair promotion, database migration/rollback rehearsal and installation of the new root-owned deploy script remain M109–M113 work. The restricted CI SSH key cannot install that script. Adding this source guard or a green CI run does not mean the existing host now enforces it.


## Read-only release smoke and guarded recovery (source implementation)

The trusted deployer writes `.release-sha` into each archived release. Worker liveness/readiness return the backend SHA captured at process startup; ordinary checkouts return null. `deployment_health.py` opens only an existing database read-only, requires its environment and exact migration checksums, and exercises essential table/column reads. It never performs setup/migrations or a full integrity scan.

`python deploy_smoke.py --api-url https://api.momiq.net --admin-url https://admin.momiq.net --backend-sha <full-sha> --mode production` performs 24 GET checks: process/readiness and release identity, all three catalog services, anonymous/invalid-token boundaries, both proxy origin boundaries, and every required panel asset. Local deployment uses the same numeric loopback origin for both surfaces and `--admin-dir <current-panel-directory>`: 22 checks, including exact served asset hashes. Empty catalogs are valid while publication remains gated. The external check verifies public routing/TLS and the expected backend SHA; it does not claim exact panel bytes unless the admin directory is supplied.

The client does not send credentials, accept cookies, follow redirects, use ambient proxies, log in or create fixtures. HTTP is accepted only for numeric loopback; other origins require HTTPS. Responses are bounded to 8 MiB, each request has a three-second socket timeout, and reports contain fixed check names/status/duration plus release/environment/schema metadata, not URLs, private bodies or secrets. Transport failures, stale workers, test login during promotion, cacheable JSON, missing assets and unexpected protected-route success fail the check. This socket timeout is not a strict whole-run deadline against a continuously trickling server; CI/deploy job timeouts remain the outer bound.

The deploy source now tests both backend and admin switches before publishing the success SHA. A failed admin smoke restores prior assets. A failed backend restart/smoke restores prior code only when that prior release's read-only checker accepts the CURRENT database; a missing checker or schema mismatch requires operator recovery. No database is automatically restored or downgraded. This compatibility check is not a complete transactional migration rollback. The initial pair, pre-migration backup/promotion procedure, installation of the root-owned script, actual restart/rollback rehearsal, HTTPS checks against the updated host and offsite recovery remain open M109–M115 work. These guards have not been installed on the hosted server by this branch.

Admin CI now discovers all `test_*.cjs` files and syntax-checks every top-level JavaScript module. Previously its explicit test list omitted the metrics, operator-access and assignment-queue suites even though all 48 tests had passed locally. A historical green run therefore must not be presented as coverage of those omitted suites.


## Mandatory pre-migration snapshot (source implementation)

Before `server.setup()` or release switching, the deploy source runs `predeploy_backup.py --data <runtime-directory> --backup-root /var/backups/momiq --revision <candidate-sha> --mode <runtime-mode>`. This uses the existing root-run backup custody; it does not give the API user new write access to the backup directory or change backup service identities. The runtime database must already exist, match the explicit environment, and have a nonempty known contiguous migration history with unchanged checksums. A newer, incomplete, altered or unrelated database is rejected. Initial bootstrap is a separate controlled operation, not an accidental fallback after a missing database.

The helper takes the existing media-maintenance lock and delegates to the WAL-safe database/private-media bundle creator. It verifies database integrity, foreign keys and hashes of referenced unexpired media before publishing a new non-overwriting snapshot. It uses the normal timestamp/random naming and manifest so existing retention rules apply; it does not extend video retention or preserve expired videos for longer. A compact `pre-migration-backup.json` in the candidate release records candidate SHA, prior schema, backup name and verification outcome, never credentials or content. Any preflight/copy/verification failure stops the script before setup or symlink replacement. The ordinary service may still accept business writes after the snapshot: it is not a zero-loss recovery point, and the snapshot must never automatically replace newer data.

Validation uses isolated pre-current/current schema databases, verifies unchanged source contents, rejects missing/foreign/invalid-history instances and nested destinations, preserves existing snapshots on name collision, checks fatal copy failure and sanitized nonzero CLI failure. The existing media/retention backup tests run alongside it. Host filesystem permissions, space, installed privileged script, migration/restart choreography, whole-service recovery and offsite encryption remain acceptance gates. No real server backup/migration/deploy was performed by these tests.


## Request authorization and operational diagnostics

The authenticated request connection revalidates credentials/permissions at transaction acquisition, including after waiting for a SQLite writer lock. Login attempt increments are also serialized. Slow body/image parsing stays outside the writer lock. The protected paths and accepted transaction ordering are documented in API_CONTRACT.md; this is not retroactive cancellation of already committed operations or full MFA rollout.

Both HTTP transports emit a single privacy-bounded `event=http` JSON record after dispatch. Aggregate only these records for application status/outcome counts and handler-duration distributions; Gunicorn/Nginx logs represent different transport scopes. Use `outcome=database_busy` with HTTP503 to distinguish SQLite contention from generic500 errors. Do not infer client receipt or proxy latency from durationMs. No raw URL, query, phone, token, media body or exception text is included. No external exporter, incident destination, paging threshold, availability SLO or mobile crash provider has been configured by this change. Hosted collection, alert delivery/retention and real contention/restart acceptance remain explicit gates.

The 2026-10-31 deployment audit found that production health advertised `testLogin=true` and `sms=false`. GET on the API health and admin root returned HTTP 200. The three repositories' default branches reported `protected=false` and no active rules on main at the time of inspection. On 2026-10-31 the owner selected audit-only. No GitHub protection settings were changed. The PR checks observed are `test` for backend/admin and both `test` and `ios-simulator` for mobile. The deployment job runs after promotion. Check branch rules and hosted configuration again before promotion.

Hosted mobile configuration rejects loopback aliases, unspecified addresses, unconfigured .invalid hosts and a nonstandard port on the production API. The backend refuses overlapping public admin and private runtime directories. Rollback rechecks the actually selected backend SHA and served admin assets before reporting recovery.

### Reapplying bootstrap on an HTTPS host

Certbot may have added certificate paths, redirects and TLS listeners to the installed Nginx site. Bootstrap compares the repository template with the installed site before package or service changes. If they differ, review both configurations and merge any new API/admin isolation and rate-limit rules into the installed TLS site. After reviewing that result, run `sudo bash /home/ubuntu/momiq-bootstrap/bootstrap.sh --preserve-reviewed-nginx`. The script keeps the installed site bytes, refreshes the shared proxy snippet, and runs `nginx -t` before reload. An unexpected site symlink target or unmanaged enabled file stops the bootstrap. Check both HTTPS hostnames and certificate renewal after any host change.

### Supplying the Tashkent service area

Set both `MOMIQ_AREA_FILE` (absolute local path) and `MOMIQ_AREA_SHA256` (lowercase SHA-256) before starting workers. The loader accepts a 2D GeoJSON Polygon or MultiPolygon, optionally inside one Feature, up to 4 MiB, with closed nondegenerate rings and longitude before latitude. Use topology-validated geometry in WGS84. A digest mismatch or malformed ring stops startup. The owner must approve the actual source, licence, revision and exact geometry before rollout. No production polygon ships in the repository. A point on the polygon boundary is admitted, holes exclude their interior. Local and test instances can run without a polygon. Restart all workers together when changing the approved digest.
