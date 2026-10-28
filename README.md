# Momiq — API va production tayyorgarligi

Joriy local/test ish tartibi: [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md). Production ishlari va bajarilish dalillari: [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md). Yangi launcher test bazasini alohida saqlaydi; production test OTP konfiguratsiyasini qabul qilmaydi.

## Ishga tushirish

Python 3.12 va `requirements.txt` dagi Pillow talab qilinadi. Windows uchun loyiha ichidagi toolchain va virtual muhitni tayyorlang:

Local va CI Python 3.12 liniyasidan foydalanadi (security patchlar yangilanishi mumkin); `requirements.txt` to‘liq `requirements.lock` fayliga yo‘naltiradi. Runtime paketlari versiyasi va PyPI release SHA-256 hashlari qat’iy belgilangan; local/CI/deploy `--require-hashes` bilan tekshiradi. Dependency o‘zgarishi full test va deploy tekshiruvini talab qiladi. Mobil Flutter/Java/Gradle/SDK versiyalari sibling app README va setup skriptlarida qayd etilgan.

```powershell
cd "D:\projects\momiq_v1\momiq_backend"
.\tool\setup-python.ps1
.\start.ps1
```

Admin: http://127.0.0.1:8080/admin/
API holati: http://127.0.0.1:8080/api/health
Admin login/paroli tanlangan data papkasidagi `admin-login.txt` fayliga yoziladi (standart launcher: `.local/local`). Bu fayl, SQLite baza va loglar Gitga kiritilmaydi.

## USB orqali Android telefon

```powershell
.\connect-phone.ps1
```

Telefon ulanganda USB debugging ruxsatini bering. `adb reverse tcp:8080 tcp:8080` telefondagi localhostni kompyuterdagi serverga bog‘laydi. Har USB qayta ulanganda skriptni qayta ishga tushiring. App avtomatik run/install qilinmaydi.

Flutter loyihasini o‘zingiz odatdagidek debug rejimida run qiling. API URL standart: `http://127.0.0.1:8080/api`. Android debug manifestida lokal HTTP yoqilgan; release uchun HTTPS kerak.

Birinchi API sinovida appdan hisobdan chiqing, telefon bilan qayta kiring. Lokal kod: **111111**. Bu SMS yuborish emas, faqat development autentifikatsiyasi. Har telefon raqamiga alohida hisob ochiladi. Oldingi mock profil avtomatik ko‘chirilmaydi.

## Nima real ishlaydi

- Mijoz autentifikatsiyasi: tasodifiy bearer token; server faqat token hashini saqlaydi, 7 kunlik amal qilish muddati.
- Profil ismi/familiyasi/rasmi; hayvonlar rasmlari; manzillar; saqlangan enagalar; til va bildirishnoma afzalliklari; yordam murojaatlari.
- Matn va rasm xabarlari SQLite bazada saqlanadi. Rasm JSON ichida base64 sifatida uzatiladi (PNG/JPEG/WebP, 3 MB gacha).
- Ishtirokchilar chati sahifalangan: ochiq suhbat 5 soniyada delta, ochiq inbox 10 soniyada yangilanadi; background/yopiq route polling qilmaydi. Yuboriladigan so‘rov shifrlanib, retry uchun bir xil ID bilan saqlanadi.
- Admin: mijozlarni qidirish, profilni tahrirlash, bloklash/ochish, murojaatlarni ko‘rish, Momiq yordam xizmati nomidan matn/rasm javobi, xabarni moderatsiya qilish. Admin amallari `audit` jadvalida.
- Mijoz boshqa hisobning xabarlariga kira olmaydi. Admin sessiyasi HttpOnly/SameSite cookie orqali ishlaydi.

Bu branchda enaga autentifikatsiyasi, profil/afzalliklar va Paynet Xolis chek orqali balans to‘ldirish ulangan. Admin QR/foizni versiya bilan saqlaydi, chek va haqiqiy tushumni tekshiradi; faqat tasdiqdan keyin atomar kredit yoziladi. Tafsilotlar `API_CONTRACT.md`da. Bu o‘zgarishlar hali productionga chiqarilmagan.

Enaga e’lonlari serverga saqlanadi va test moderatsiyasi orqali katalogda ko‘rinadi; bu haqiqiy MyID tasdig‘i emas. Katalog sahifalash, jadval/sig‘im filtrlari va taxminiy koordinatalar asosida masofa saralash bilan ishlaydi. Haqiqiy mijoz–enaga chati, blok/shikoyat va auditli moderatsiya bor. Uchala xizmat uchun server quote, qabul/komissiya, bekor/qaytim, ikki tomon boshlash/yakunlash tasdig‘i, kunlik parvarish, o‘zgarmas sharh va admin ko‘radigan nizo local/test muhitida ulangan. Ichki bildirishnoma va 15/30 daqiqalik eslatmalar bor. Hozirgi sxema 17; bajarilgan va ochiq native sinovlar checklistda. Production/staging booking yo‘llari yopiq, tashqi push/SMS/MyID hali ulanmagan.

Backendga ulangan rejimda hayvonlar serverda saqlanadi. Eski offline/test mock rejimida hayvonlar session ichida saqlanish qoidasi qoladi.

## Ma’lumotlar

Baza: `data/momiq.sqlite3`. Server qayta ochilganda ma’lumotlar qoladi. SQLite backup API orqali nusxa oling; ishlayotgan bazaning faqat asosiy faylini WAL faylisiz ko‘chirmang.
Sinov uchun `+998 90 000 00 01` hisobida `Sinov Mijoz` mavjud; bu haqiqiy mijoz emas.

## API

| Method | Endpoint | Kirish |
|---|---|---|
| GET | /api/health | ochiq |
| POST | /api/auth/login | phone, code |
| POST | /api/auth/logout | bearer |
| GET/PUT | /api/me | bearer, faqat o‘z hisobi |
| GET/POST | /api/messages | bearer, faqat o‘z xabarlari |
| POST | /api/admin/login | username, password |
| POST | /api/admin/logout | admin cookie |
| GET | /api/admin/users | admin cookie |
| PUT | /api/admin/users/:id | account va/yoki blocked |
| GET/POST | /api/admin/users/:id/messages | admin cookie |
| DELETE | /api/admin/messages/:id | admin cookie, moderatsiya |

## Testlar

```powershell
.\.venv\Scripts\python.exe -m unittest -v
cd ..\momiq_app
.\tool\flutter.ps1 analyze
.\tool\flutter.ps1 test
.\tool\flutter.ps1 test --dart-define=MOMIQ_INTEGRATION=true test/customer_api_integration_test.dart
```

Oxirgi buyruq ishlayotgan localhost APIga ulanadi va belgilangan sinov hisobini ishlatadi. Oddiy testlar tarmoqsiz mock rejimda ishlaydi.

## Serverga ko‘chirish

Bu versiya localhost development uchun: Python stdlib HTTP serveri va doimiy 111111 kodi bilan internetga ochmang.
Mobil token secure storage’ga ko‘chirildi; uning va boshqa bajarilgan bosqichlarning dalillari checklistda. SMS/OTP, MyID, public release, object storage, tashqi push va production backup/monitoring bo‘yicha qolgan talablar ham shu ro‘yxatda yuritiladi. Katalog va admin foydalanuvchi/e’lon ro‘yxatlari serverda sahifalanadi. Mijozdagi URL:

```powershell
flutter run --dart-define=MOMIQ_API_URL=https://api.example.uz/api
```

SQLite ma’lumotlarini keyin PostgreSQL/object storage ga ko‘chirish mumkin. `MOMIQ_DATA_DIR`, `MOMIQ_HOST`, `MOMIQ_PORT`, birinchi start uchun `MOMIQ_ADMIN_PASSWORD` muhit o‘zgaruvchilari qo‘llanadi. Standart bind faqat 127.0.0.1.

## Clone from GitHub

Clone the repositories into sibling folders. The backend detects `momiq_admin`, falls back to `momiq_admin_panel`, or uses an explicit `MOMIQ_ADMIN_DIR`.

```sh
git clone https://github.com/umar200000/momiq_backend.git
git clone https://github.com/umar200000/momiq_admin.git momiq_admin_panel
cd momiq_backend
python -m pip install --require-hashes -r requirements.txt
python server.py
```

Open http://127.0.0.1:8080/admin/ . Local credentials are generated on the first start.

## Roles and sitter listings
Login accepts optional `role` (`customer` / `sitter`). Memberships accumulate per account; existing users are migrated from their saved sitter profile. `GET/PUT /api/me/listings` stores up to three validated service types for the authenticated owner. PUT requires the loaded `_revision` (428 when missing, 409 when stale). Responses include server-owned `moderation` status/reason per service. Admins review using `POST /api/admin/listings/{userId}/{service}/review` with `_revision`, `decision` (approve/reject/suspend), `reason` and explicit `testOnly`.

`GET /api/sitters` derives discovery from active approved listings, matching profile/price fingerprints, unblocked sitter accounts and balance >= 15,000 UZS. Legacy demo `sitters` rows are retained only as existing references. Private street addresses are replaced by an approximate map point; public image derivatives are resized, oriented and stripped of metadata during approval. Originals and payment receipts remain unchanged. Existing chat remains usable after discovery removal; new client conversations require current discovery eligibility.

MyID is deferred: approval currently requires `testOnly=true` in a non-production environment. These records explicitly return `identityVerified=false`; production discovery remains empty until actual verification is implemented. Seeding does not approve or fund fixtures automatically. Complete a TEST profile, review its TEST top-up, then explicitly approve its TEST listing in the local admin panel. Local/test bookings enforce capacity and charge commission atomically on acceptance; production rollout and unfinished lifecycle work remain tracked in `PRODUCTION_CHECKLIST.md`.

## QR recipient and payment history

Platform settings version the QR image, `recipientName`, `paymentInstructions`, `qrActive` and commission together. Activating QR display requires a recipient name and image. Migration 4 pauses existing QR display until an administrator records the recipient and explicitly activates it; already paid receipts on historic versions remain submittable. The receipt endpoint includes the request's original `paymentSnapshot`, so later QR changes cannot alter the evidence under review. Pausing display in Momiq does not deactivate the QR at the external payment provider. No payment gateway or automatic receipt credit is enabled.

Migration 5 preserves old requests and adds payer-supplied `payerReference` and `paidAt`. New top-up requests require at least one; timestamps must include a timezone and are normalized to UTC. These are unverified evidence, separate from the administrator's independently verified `transferReference`. Retrying an existing request must preserve all evidence fields. Old requests without these fields remain readable and their unchanged idempotent retries still work. Deploy the compatible app before inviting new payments with older clients.

Migration 6 adds owner-scoped in-app notifications for top-up decisions and listing moderation. The event is inserted in the same transaction as the decision and deduplicated by its business source. `GET /api/notifications?before=<cursor>` returns 20 notices, `nextCursor` and `unreadCount`; `POST /api/notifications/<id>/read` is owner-checked and idempotent. Notice content is immutable; read state persists. Existing decisions are not backfilled. These transactional notices appear regardless of optional order/chat/care preferences. Booking transitions, participant chat messages and care journal changes now share their transaction with in-app notices. Chat/care notices contain only a safe event type and internal target, never message text, medicine instructions or media. External push delivery and delivery-provider monitoring remain pending.

Migration 7 rebuilds the top-up table transactionally to add `needs_info` and revisions while preserving existing rows, incoming references and wallet entries. Existing evidence is imported as a single `migrated` snapshot; missing historical transitions are not invented. New evidence and every decision append immutable history. Receipt images are retained once per hash, and a previously replaced image still cannot be claimed by a different request.

Admin review requires the loaded `revision` and supports `approve`, `reject`, `request_info`. Identical decision retries remain idempotent. A sitter may resubmit only a `needs_info` or `rejected` request through `POST /api/wallet/topups/<id>/amend`, providing a fresh action `requestId`, original QR version, loaded revision, full evidence and renewed consent. Resubmission returns it to `pending` without credit. Stale reviews/amendments fail with 409. Owner-scoped `GET /api/wallet/topups/<id>` and `/history?before=<revision>` expose status/history; historical images use `/history/<revision>/receipt`. Admin history uses the corresponding `/api/admin/topups/...` path and includes the actor. Deploy the revision-aware admin together with this API; older review forms fail closed with 428.


Participant chat uses `/api/conversations` for authenticated customer/sitter inboxes, cursor/delta pages, private attachment access and monotonic read acknowledgements. The app retains legacy admin replies as separately labelled support history. Migration 8 adds conversation tables without rewriting old data. See API_CONTRACT.md for exact gates, quotas, retries and remaining booking/push/operator-role limitations.


Migration 14 adds participant-scoped booking care instructions and daily reports. Customers append per-animal instructions/schedules; sitters record today’s care only for active bookings. Corrections preserve history, stale revisions conflict, and exact retries are deduplicated. The server uses Asia/Tashkent to authorize report dates. Completed/cancelled history remains read-only. Migration 18 separately adds private daily videos; automatic care reminders remain open.

Video runtime: run `./tool/setup-video.ps1` on Windows (project-only FFmpeg 9.0.2, SHA-256 checked). Linux needs the distribution `ffmpeg` package; CI and bootstrap install it, and deploy refuses to proceed without ffmpeg/ffprobe. Binary source: [Gyan official release mirror](https://github.com/GyanD/codexffmpeg/releases/tag/9.0.2). It is a server/development tool, not bundled into the mobile application. Dependency license/security maintenance remains part of release operations.

Videos are still local/test only with the booking API. Server UTC enforces Asia/Tashkent morning `[07:00,11:00)` and evening `[18:00,22:00)`, 10–60 seconds, one report per booking/pet/day/slot. Only an active booking's sitter uploads; participants view authenticated byte-range playback. MP4/MOV H.264/HEVC up to 1080p/60fps/32 MiB is fully decoded into H.264/AAC MP4 and a JPEG poster with metadata stripped. Original uploads are temporary. Two transfers/decoders per process, bounded size/time and rate limits protect the synchronous implementation; peak-load/queue sizing is still M007/M131, not proven production capacity.

Private derivatives live under `MOMIQ_DATA_DIR/care-videos`. Database-only backups are now insufficient: use `python backup_bundle.py --data-dir <instance> --destination <new-folder>` and `python backup_bundle.py --verify <folder>`. A complete bundle contains a SQLite API snapshot, every referenced video/poster, and a SHA-256 manifest; an incomplete copy is never published. Restore into a stopped, separate instance and verify before switching traffic. Daily backup tooling creates verified bundles. Managed timestamp-named bundles rotate after the existing 14-day database backup limit, or earlier when any contained video expires. Expiry pruning only touches verified generated bundles and preserves unknown files/custom backups. Offsite copies and manual exports require the same retention policy from their operator. Disk alerts, offsite encryption and a hosted restore drill remain M114/M115 release gates. Reinstall updated bootstrap/service/proxy/backup configuration before hosted rollout (150-second video processing response budget); merely pushing application code does not update those installed files.
Migration 15 adds completed-booking reviews and server-derived reputation. Each customer can submit one immutable 1–5 star review per completed booking; text and rating cannot be edited after submission. Author withdrawal/restoration and reasoned admin moderation change visibility only. TEST reviews never affect ratings. The mobile app uses an encrypted retry draft; the admin review queue preserves decision history. See API_CONTRACT.md for routes and rollout gates.

Migration 16 adds private customer/sitter support tickets with optional booking context, image attachments, immutable replies, revision conflicts and encrypted mobile retry drafts. Admin replies identify Momiq support; resolution does not affect money or booking state. Owner notices are transactional. Historical account requests remain readable as an archive. See API_CONTRACT.md for bounds and remaining assignment, dispute and operator-role work.

Migration 17 adds participant-owned no-show/service disputes, private evidence, explicit admin decisions and bounded commission compensation. Confirmed incidents are deduplicated per booking/account, with a rolling 30-day review flag at three and audited emergency exclusions. A complaint itself never counts as a confirmed no-show. The 48-hour deadline flags overdue review without automatic money movement. See API_CONTRACT.md for outcomes and outstanding operator/push work.


Schema 19 implements approved video retention: 30 days after terminal booking time and any dispute resolution (whichever is later); an open dispute/ongoing service holds the reports. Every playback/poster request checks expiry, so a delayed cleanup job cannot expose expired media. Immutable report metadata remains, while a separate retirement record tracks retryable file removal. Local/test expiry workers process bounded batches; hosted `momiq-media-retention.timer` and `momiq-backup-retention.timer` run every minute. Deploy requires these installed units and starts the timers after a healthy switch. Backup and media retirement share a cross-process file lock; a root-run backup preserves the data directory owner's access to that lock. File retirement never recursively removes unknown content. Operators see failed job exits and must investigate rather than weakening retention checks.
