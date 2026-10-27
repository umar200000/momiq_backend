# Momiq — API va production tayyorgarligi

Joriy local/test ish tartibi: [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md). Production ishlari va bajarilish dalillari: [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md). Yangi launcher test bazasini alohida saqlaydi; production test OTP konfiguratsiyasini qabul qilmaydi.

## Ishga tushirish

Python 3.12 va `requirements.txt` dagi Pillow talab qilinadi. Windows uchun loyiha ichidagi toolchain va virtual muhitni tayyorlang:

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
- App va admin chat oynasi har 3 soniyada yangilanadi. Offline yuborish muvaffaqiyat sifatida ko‘rsatilmaydi; foydalanuvchi qayta urinadi.
- Admin: mijozlarni qidirish, profilni tahrirlash, bloklash/ochish, murojaatlarni ko‘rish, enaga nomidan matn/rasm javobi, xabarni moderatsiya qilish. Admin amallari `audit` jadvalida.
- Mijoz boshqa hisobning xabarlariga kira olmaydi. Admin sessiyasi HttpOnly/SameSite cookie orqali ishlaydi.

Bu branchda enaga autentifikatsiyasi, profil/afzalliklar va Paynet Xolis chek orqali balans to‘ldirish ulangan. Admin QR/foizni versiya bilan saqlaydi, chek va haqiqiy tushumni tekshiradi; faqat tasdiqdan keyin atomar kredit yoziladi. Tafsilotlar `API_CONTRACT.md`da. Bu o‘zgarishlar hali productionga chiqarilmagan.

Buyurtmalar va komissiya yechish/qaytarish hali ulanmagan. Enaga e’lonlari serverga saqlanadi; mijoz katalogiga moderatsiya orqali nashr qilish hali alohida bajariladi. Push/SMS/MyID hali ulanmagan. Hozirgi mijoz–admin chatini haqiqiy mijoz–enaga suhbatiga aylantirish ham qolgan.

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
Mobil token secure storage’ga ko‘chirildi; uning va boshqa bajarilgan bosqichlarning dalillari checklistda. SMS/OTP, MyID, public release, object storage, katalog paginatsiyasi, push va production backup/monitoring bo‘yicha qolgan talablar ham shu ro‘yxatda yuritiladi. Mijozdagi URL:

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
python -m pip install -r requirements.txt
python server.py
```

Open http://127.0.0.1:8080/admin/ . Local credentials are generated on the first start.

## Roles and sitter listings
Login accepts optional `role` (`customer` / `sitter`). Memberships accumulate per account; existing users are migrated from their saved sitter profile. `GET/PUT /api/me/listings` stores up to three validated service types for the authenticated owner. PUT requires the loaded `_revision` (428 when missing, 409 when stale). Responses include server-owned `moderation` status/reason per service. Admins review using `POST /api/admin/listings/{userId}/{service}/review` with `_revision`, `decision` (approve/reject/suspend), `reason` and explicit `testOnly`.

`GET /api/sitters` derives discovery from active approved listings, matching profile/price fingerprints, unblocked sitter accounts and balance >= 15,000 UZS. Legacy demo `sitters` rows are retained only as existing references. Private street addresses are replaced by an approximate map point; public image derivatives are resized, oriented and stripped of metadata during approval. Originals and payment receipts remain unchanged. Existing chat remains usable after discovery removal; new client conversations require current discovery eligibility.

MyID is deferred: approval currently requires `testOnly=true` in a non-production environment. These records explicitly return `identityVerified=false`; production discovery remains empty until actual verification is implemented. Seeding does not approve or fund fixtures automatically. Complete a TEST profile, review its TEST top-up, then explicitly approve its TEST listing in the local admin panel. Booking, capacity locking and commission charging remain separate unfinished work in `PRODUCTION_CHECKLIST.md`.

## QR recipient and payment history

Platform settings version the QR image, `recipientName`, `paymentInstructions`, `qrActive` and commission together. Activating QR display requires a recipient name and image. Migration 4 pauses existing QR display until an administrator records the recipient and explicitly activates it; already paid receipts on historic versions remain submittable. The receipt endpoint includes the request's original `paymentSnapshot`, so later QR changes cannot alter the evidence under review. Pausing display in Momiq does not deactivate the QR at the external payment provider. No payment gateway or automatic receipt credit is enabled.

Migration 5 preserves old requests and adds payer-supplied `payerReference` and `paidAt`. New top-up requests require at least one; timestamps must include a timezone and are normalized to UTC. These are unverified evidence, separate from the administrator's independently verified `transferReference`. Retrying an existing request must preserve all evidence fields. Old requests without these fields remain readable and their unchanged idempotent retries still work. Deploy the compatible app before inviting new payments with older clients.
