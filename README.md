# Momiq — lokal profil va chat backend

## Ishga tushirish

Python 3.12+ yetarli. Qo‘shimcha paket talab qilinmaydi.

```powershell
cd "D:\full projects\momiq project\momiq_backend"
.\start.ps1
```

Admin: http://127.0.0.1:8080/admin/
API holati: http://127.0.0.1:8080/api/health
Admin login/paroli birinchi startda `data/admin-login.txt` fayliga yoziladi. Bu fayl, SQLite baza va loglar Gitga kiritilmaydi.

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

Buyurtmalar, to‘lov, enaga e’lonlari va enaga appining backendga ko‘chirilishi bu modulga kirmaydi; avvalgi mock oqimlari saqlangan. Push bildirishnomalari/SMS provayderi hali ulanmagan. Admin javoblari mijoz appiga keladi; enaga appi hozir bu APIga autentifikatsiya qilinmagan.

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
python -m unittest -v
cd ..\momiq_app
flutter analyze --no-pub
flutter test --no-pub
flutter test --no-pub --dart-define=MOMIQ_INTEGRATION=true test/customer_api_integration_test.dart
```

Oxirgi buyruq ishlayotgan localhost APIga ulanadi va belgilangan sinov hisobini ishlatadi. Oddiy testlar tarmoqsiz mock rejimda ishlaydi.

## Serverga ko‘chirish

Bu versiya localhost development uchun: Python stdlib HTTP serveri va doimiy 111111 kodi bilan internetga ochmang.
Production bosqichida SMS provayder/OTP challenge, HTTPS reverse proxy, production HTTP server/framework, tokenni platformaning secure storage xizmatiga ko‘chirish, object storage, paginatsiya, push/WebSocket, backup va monitoring qo‘shiladi. Mijozdagi URL:

```powershell
flutter run --dart-define=MOMIQ_API_URL=https://api.example.uz/api
```

SQLite ma’lumotlarini keyin PostgreSQL/object storage ga ko‘chirish mumkin. `MOMIQ_DATA_DIR`, `MOMIQ_HOST`, `MOMIQ_PORT`, birinchi start uchun `MOMIQ_ADMIN_PASSWORD` muhit o‘zgaruvchilari qo‘llanadi. Standart bind faqat 127.0.0.1.

## Clone from GitHub

Clone the repositories into sibling folders. Keep the admin folder named `momiq_admin_panel` because the backend serves assets from that path.

```sh
git clone https://github.com/umar200000/momiq_backend.git
git clone https://github.com/umar200000/momiq_admin.git momiq_admin_panel
cd momiq_backend
python server.py
```

Open http://127.0.0.1:8080/admin/ . Local credentials are generated on the first start.
