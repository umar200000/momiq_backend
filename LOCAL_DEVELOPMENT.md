**Momiq local va test muhiti**

Backend va admin repolari bir ota papkada `momiq_backend` va `momiq_admin` nomlari bilan turadi. Eski `momiq_admin_panel` nomi ham fallback sifatida qo‘llanadi; `MOMIQ_ADMIN_DIR` aniq yo‘lni belgilaydi.

Python 3.12+ va Flutter 3.44.5 kerak. CI Python 3.12 / Flutter 3.44.5 ishlatadi. App papkasida `./tool/setup-flutter.ps1` loyiha uchun alohida SDK o‘rnatadi; keyingi buyruqlarda `./tool/flutter.ps1` ishlatiladi. Global SDK o‘zgarmaydi. Windowsdagi global Flutter 3.47.8 test processida 0xc0000005 native qulash kuzatildi; CI bilan bir xil 3.44.5 SDK’da to‘liq suite o‘tdi. Bu kuzatuv upstream xatoning aniq ildiz sababi topildi degani emas. Git long-path sozlamasi faqat shu SDK clone’ida yoqiladi. Mahalliy Python 3.15.1, Java/NDK uyg‘unligi hali M010 doirasida tekshiriladi. iOS simulator/build uchun macOS kerak; signing yakuniy bosqichda.

**Ishga tushirish**

Backend papkasidan:

```powershell
./start.ps1 -Port 8081 -Seed
```

Bu `.local/preview` ichida alohida SQLite bazasi yaratadi va serverni yashirin fonda ochadi. Admin: `http://127.0.0.1:8081/admin/`. Admin paroli `.local/preview/admin-login.txt` ichida; Gitga kirmaydi. Takror ishga tushirish ayni serverni ishlatadi. Portda boshqa baza/eski server tursa skript uni o‘chirmaydi, boshqa port tanlashni talab qiladi.

Fixtures: `998000000001` mijoz; `998000000002` uyda qarash; `998000000003` uyga borib qarash; `998000000004` shaxsiy enaga. Faqat local/test kirish kodi `111111`. Ismlar `TEST` bilan belgilanadi, rasmlar sintetik, katalog haqiqiy xizmatni anglatmaydi. Bron/chat/hisobot fixturelari tegishli modellar tayyor bo‘lgach qo‘shiladi.

Emulator yoki telefon ulangan bo‘lsa:

```powershell
./start.ps1 -Port 8081 -Seed -App -Device emulator-5554
```

Skript adb reverse o‘rnatadi, mavjud bo‘lmasa MapKit lokal konfiguratsiya namunasini nusxalaydi va shu API bilan Flutter’ni ishga tushiradi. Birinchi o‘rnatishda app papkasida `flutter pub get` bajarilgan bo‘lishi kerak. Xarita uchun haqiqiy kalit alohida kerak; bo‘sh namuna xarita integratsiyasi tayyor degani emas.

Qo‘lda test ma’lumotlari:

```powershell
python seed_test_data.py --data-dir .local/another-preview
python seed_test_data.py --data-dir .local/another-preview --clean
```

Seed faqat yangi yoki o‘z markeriga ega local/test papkaga yozadi. Qayta ishga tushirish dublikat qilmaydi va tahrirlangan fixture ustidan yozmaydi. Clean faqat seedning hisoblari/yozuvlarini o‘chiradi; begona foydalanuvchi ularga bog‘langan bo‘lsa rad etadi. Ishlab turgan real bazani seed papkasiga ko‘chirmang. Hosted muhitda seed ishlamaydi.

**Muhitlar**

- `local`: HTTP localhost, test login; eski bazalar uchun `data/` default saqlangan, yangi launcher `.local/local` yoki `.local/preview` ishlatadi.
- `test`: avtomatik sinov bazasi; hosted ma’lumotlar ishlatilmaydi.
- `staging`: alohida HTTPS host va mutlaq `MOMIQ_DATA_DIR`; test login faqat `MOMIQ_ALLOW_TEST_LOGIN=1` bilan. Remote staging hali yaratilmagan.
- `production`: alohida mutlaq data yo‘li, test login qat’iy taqiqlangan. Hozir SMS yo‘q, shu sabab mijoz kirishi yopiq bo‘ladi. Amaldagi server test-login konfiguratsiyasi almashtirilmaguncha bu o‘zgarishni main’ga deploy qilmang.

Runtime database ichida muhit belgisi bor; boshqa muhitga ko‘rsatish startup’da rad etiladi. Legacy bazani birinchi ochishdan oldin deploy/backup rejasiga rioya qilinadi. `.env.example` hujjat namunasidir, dotenv avtomatik o‘qilmaydi.

App sozlamalari `config/local.json`, `config/production.json`, `config/staging.example.json`. Hosted staging domeni tasdiqlangach `config/staging.local.json` yaratiladi. Staging namunasidagi `.invalid` host ishlaydigan server emas.

```powershell
./tool/flutter.ps1 run --dart-define-from-file=config/local.json
```

Local build production API’ga ulanmaydi; release local konfiguratsiyani rad etadi. Login server health’dagi muhitni tekshiradi, production’da SMS/test-login flaglarini tekshiradi. Token saqlanganda muhit+API manzili ham saqlanadi; eski yoki boshqa muhit tokeni yuborilmasdan tozalanadi.

**Tekshiruv**

```powershell
python -m unittest -q
# App papkasida:
./tool/flutter.ps1 analyze --no-pub
./tool/flutter.ps1 test --no-pub --concurrency=1
./tool/flutter.ps1 test --no-pub --dart-define=MOMIQ_INTEGRATION=true --dart-define=MOMIQ_API_URL=http://127.0.0.1:8081/api test/customer_api_integration_test.dart
```

Integration testi faqat aniq belgilangan lokal test hisobida profil/hayvon/sozlamani yozadi. Windows umumiy test runner’i suite yuklashda ulanishni yo‘qotsa, `tool/check-windows.ps1` har faylni alohida processda bajaradi, `.local/test-results/summary.json` va alohida loglarga exit kodlarini saqlaydi. Muvaffaqiyatsiz testlar yashirilmaydi.
