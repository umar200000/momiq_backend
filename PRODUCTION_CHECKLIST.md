**Momiq productionga tayyorlash vazifalari**

Holat: foydalanuvchi barcha qolgan takliflarni tasdiqladi, bosqichma-bosqich amalga oshirish boshlandi. Sana: 2026-10-27. Vazifalar faqat tegishli tekshiruvdan keyin yopiladi.

**Foydalanuvchi tasdiqlagan mahsulot qarorlari**

- Birinchi reliz Android va iOS uchun. Production signing ikkala platformada ham yakuniy bosqichda; hozir funksional ish va mavjud vositalar bilan test davom ettiriladi.
- Dastlabki hudud Toshkent; uchala xizmat ham chiqariladi. Toshkent chegarasining aniq xarita poligoni alohida belgilanadi.
- Har uchala xizmatda narx bir hayvon uchun bir kunga belgilanadi; har xizmatning tarifini enaga alohida kiritadi. Bir xil tarifdagi hayvonlar uchun jami = kunlik tarif × hayvonlar soni × kunlar soni. Turli tariflar bo‘lsa har hayvonning kunlik tarifi yig‘iladi. Uyga borib qarash ham kunlik, bitta tashrif narxi emas.
- Shaxsiy enaga bir vaqtda bittadan ortiq hayvon qaramaydi; bu cheklov tanlashda ham, parallel buyurtmalarda ham tekshiriladi. Boshqa xizmatlarning sig‘im qoidalari saqlanadi.
- Enaga Momiq balansini to‘ldiradi. Platforma mijoz topib bergan xizmat uchun enaga narxidan komissiya oladi va uni enaga balansidan yechadi.
- Boshlang‘ich komissiya 10%; foizni admin panelda kiritish/o‘zgartirish mumkin bo‘lishi kerak.
- Enaga balansi 15 000 so‘mdan past bo‘lsa unga yangi mijoz topib berilmaydi. Aynan 15 000 so‘m chegara bo‘yicha ruxsat etilgan; komissiyaga yetarlilik alohida tekshiriladi.
- Mijoz xizmat pulini enaga bilan o‘zi kelishib to‘laydi. Momiq bu pulni qabul qilmaydi, enagaga tarqatmaydi va xizmat puli refundini bajarmaydi.
- Balans Paynet Xolis orqali qo‘lda tasdiqlanadigan tartibda to‘ldiriladi: admin QR kod yuklaydi, enaga provayder ilovasida QR orqali to‘laydi va Momiqdagi balans to‘ldirish oqimida chek jo‘natadi. Admin chekni ham, haqiqiy tushumni ham tekshirgach balansga pul qo‘shadi. Chekning o‘zi avtomatik kredit uchun asos bo‘lmaydi.
- Click va Payme birinchi relizga kirmaydi; keyingi yangilanishlarda qo‘shilishi mumkin. Hozir avtomatik payment API/webhook integratsiyasi talab qilinmaydi.
- Balansdagi ishlatilmagan qoldiq qaytarib berilmaydi, karta/naqd pulga chiqarish funksiyasi bo‘lmaydi. Komissiyani qaytarish tasdiqlangan holatda faqat Momiq balansiga tiklashdir. Bu qoida balans to‘ldirishdan oldin ko‘rsatiladi va rozilik versiyasi qayd etiladi; hisobni o‘chirish ekranida ham qoldiq taqdiri tushuntiriladi.
- Enagani tekshirish MyID orqali bo‘ladi. Kelishuv tugamagani sabab integratsiya yakuniy bosqichga qoldirildi; testda haqiqiy tekshiruvdan o‘tgan degan belgi berilmaydi.
- 30 kun ichida 3 ta kech bekor qilish yoki tasdiqlangan kelmaslik holati admin ko‘rigiga chiqariladi; favqulodda vaziyatlar hisobga olinadi. Bir hodisa ikki marta sanalmaydi; oddiy tasdiqlanmagan shikoyat kelmaslik sifatida hisoblanmaydi.
- Kelmaslik nizosini ko‘rib chiqish muddati 48 soat. Xizmat boshlanmagani tasdiqlansa komissiya enaga balansiga qaytariladi; mijozning enagaga bergan xizmat pulini Momiq qaytarmaydi.
- Quyidagi bekor qilish, javobsiz so‘rov, komissiya bazasi/yechish va cheklovlar ham tasdiqlangan. SMS provayder integratsiyasi ham foydalanuvchi ko‘rsatmasi bilan MyID va signing kabi yakuniy bosqichga qoldirilgan.

**Tasdiqlangan qo‘shimcha biznes qoidalari**

Quyidagi takliflar foydalanuvchining «Qolgan takliflaringni ham tasdiqlayman» xabari bilan tasdiqlandi. Aniq qiymat taklif etilmagan masalalar (kunlik tashrif jadvali, hudud chegarasi) tasdiqlangan deb to‘qib chiqarilmaydi.

1. Komissiya bazasi bronning tasdiqlangan jami xizmat summasi bo‘lsin. Masalan, bir mushuk uchun kuniga 500 000 so‘m × 2 mushuk × 3 kun = 3 000 000 so‘m; 10% komissiya = 300 000 so‘m. 500 000 so‘m faqat misol, standart tarif emas. Mijoz xizmat pulini enagaga o‘zi to‘laydi. Narxlash birligi va jami summani komissiya bazasi qilish tasdiqlangan.
2. Kun hisoblashda boshlanish/tugash kuni, topshirish/qabul qilish vaqti va uyga borib qarashda kunlik tashrif soni/davomiyligini kelishish kerak. Tarif birligi barcha xizmatlarda bir hayvon uchun bir kun bo‘lib qoladi.
3. Komissiya mijoz so‘rov yuborganida emas, enaga buyurtmani qabul qilganida bir marta yechilsin. Qabul qilishdan oldin enaga jami summa, foiz va yechiladigan pulni ko‘rsin. E’lonni keyin tahrirlash mavjud buyurtma summasini o‘zgartirmasin.
4. Qabul qilishdan oldingi sarflash mumkin bo‘lgan balans kamida max(15 000 so‘m, komissiya) bo‘lsin. Masalan, balans 20 000, komissiya 30 000 bo‘lsa qabul qilish uchun to‘ldirish talab etiladi. Yechilgandan keyin balans 15 000 dan pastlashsa qabul qilingan buyurtma davom etadi, yangi mijoz olish to‘xtaydi. Bir vaqtdagi qabul qilishlar balansni manfiy qilmasin.
5. Balansi yetmagan enaga yangi tavsiya/qidiruvga chiqmasin; eski havola yoki saqlangan profil orqali ham yangi so‘rov/ilk chat bilan chetlab o‘tilmasin. Oldingi faol buyurtma, chat va parvarish ishlashda davom etsin; balans yetarli bo‘lganda qolgan talablar ham bajarilgan bo‘lsa qayta ko‘rinsin.
6. Foiz o‘zgarishi yangi narx takliflariga tatbiq etilsin. Mijoz tasdiqlab yuborgan so‘rovda foiz, summa va qabul muddati saqlansin; admin foizni o‘zgartirishi o‘sha so‘rov/buyurtmani orqadan qayta hisoblamasin. Pul eng kichik birlikda aniq hisoblanib, yaxlitlash qoidasi bir xil qo‘llansin.
7. Javob berish muddati 2 soat yoki xizmat boshlanishigacha qolgan vaqt — qaysi biri oldin bo‘lsa. Javobsiz so‘rov eskiradi, komissiya olinmaydi; mijoz boshqa enaga tanlashi mumkin. Bir hayvonning ayni vaqtdagi bir nechta so‘rovidan faqat bittasi tasdiqlanishi mumkin.
8. Qabul qilinmagan so‘rovni mijoz bekor qilsa yoki enaga rad etsa, komissiya yo‘q. Qabul qilingan buyurtma xizmat boshlanishidan oldin bekor qilinsa, yechilgan komissiya enaga balansiga to‘liq qaytarilsin. Mijozning xizmat puli bo‘yicha Momiq avtomatik jarima yoki refund qilmaydi.
9. Kech bekor qilish chegarasi xizmat boshlanishidan oldingi 24 soat deb belgilansin; avtomatik pul jarimasi bo‘lmasin, enaga bekor qilsa mijozga boshqa variantlar ko‘rsatilsin. 30 kun/3 holat va favqulodda vaziyatni hisobga olish qoidasi allaqachon tasdiqlangan; 24 soatlik chegara ham tasdiqlangan.
10. Kelishilgan vaqtga kelmaslikda 15 daqiqadan keyin eslatma/aloqa taklifi, 30 daqiqadan keyin kelmadi deb murojaat qilish imkoniyati bo‘lsin. 15/30 daqiqalik chegaralar ham tasdiqlangan; 48 soatda ko‘rib chiqish va xizmat boshlanmaganida komissiyani balansga qaytarish tasdiqlangan.
11. Xizmat boshlanganidan keyingi bekor qilish/nizoda komissiya avtomatik qaytarilmasin; admin dalil va xizmat holatiga qarab sabab bilan to‘liq/qisman qaytarishi mumkin. Bu mijoz–enaga o‘rtasidagi xizmat puli hisob-kitobini boshqarish emas.
12. Xato yozilgan balansni tuzatish va haqiqiy xato/dublikat to‘lov bo‘yicha murojaat alohida auditli ko‘rib chiqilsin. Bu ishlatilmagan qoldiqni erkin chiqarish imkoniyati emas; noto‘g‘ri kreditni jurnal orqali tuzatish tartibi kelishiladi.

Yakuniy bosqichga qoldirish SMS/MyID/signing bajarildi degani emas: ommaviy relizdan oldin ular yopiladi. Hozir iOS kod/build mosligi tekshiriladi; haqiqiy iPhone/TestFlight/APNs tekshiruvlari tegishli Apple hisoblari va signing tayyor bo‘lgach yakunlanadi.

Maqsad: mijoz enaga topib, buyurtma berishi; enaga uni qabul qilib, parvarish hisobotini yuborishi; hisob-kitob, yordam va boshqaruv jarayonlari ishonchli ishlashi. Vazifalar ilova/backend bo‘yicha emas, yakuniy foydalanuvchi jarayonlari bo‘yicha jamlangan.

Mock/test ma’lumotlari qo‘shish va keyingi ish davomida zarur deploy uchun foydalanuvchi ruxsati bor. Test hisoblari, media va to‘lovlar aniq ajratiladi; haqiqiy mijoz ma’lumotlari testga ko‘chirilmaydi. Hozirgi ro‘yxatni tayyorlash production holatini o‘zgartirishni anglatmaydi.

Har bir katak faqat kod, tegishli tekshiruv va natija dalili mavjud bo‘lganda belgilanadi. Ish boshlanganda mas’ul, bog‘liqlik, commit/PR va test dalili shu ID ostida yoziladi. Shartli vazifa faqat mahsulot qarori yozilgandan keyin qo‘llanmaydi deb yopiladi; jimgina tashlab ketilmaydi. Quyidagi ro‘yxat auditda ma’lum bo‘lgan ko‘lamni qamraydi; ish davomida topilgan yangi holatlar yangi ID bilan qo‘shiladi.

**Bajarilish jurnali — 2026-10-27**

- M061/M136 yopildi: QR/chek/rozilik/retry UI va admin tekshiruvi API bilan ulandi. Android preview APK’da 15 000 so‘m test balans, 10% komissiya, tasdiqlangan so‘rov va aynan 1 ledger yozuvi ko‘rildi (`.local/wallet-android-balance.png`, `.local/wallet-android-history.png`). Admin UI dalili `.local/wallet-admin-approved.png`. Balans va jurnal GET javobi bir DB snapshotdan o‘qiladi; parallel kredit paytidagi izchillik regressioni bilan jami 40 Python testi o‘tdi. Bron/komissiya yechish, qoralama/aniqlashtirish va QR saqlash alohida ochiq bandlar bo‘lib qoladi.

- Lokal oqim dalili: `TEST boarding` hisobidan sintetik chek yuborildi, pending paytida balans 0; admin UI tasdiqlagach 1 500 000 tiyin va aynan 1 ledger yozuvi. Haqiqiy pul o‘tkazilmagan. Tasdiqlangan chek screenshot’i `.local/wallet-admin-approved.png`. Androidda barcha sessiyalardan chiqish ham amalda tekshirildi.
- M010/M119/M126: Android build global C diskida joy tugashi sabab yiqildi. Shu buildning engine kesh fayllari D diskiga ko‘chirildi, qisman extraction nusxalari saqlandi; wrapper Gradle/TEMP/TMP’ni loyiha D diskiga yo‘naltiradi. Keyingi x64 debug APK muvaffaqiyatli (448,6 s); preview API porti dastlab default8080 bo‘lgani aniqlanib, 8081 bilan qayta build ham o‘tdi (82,6 s). Maxsus live API Flutter testi ham o‘tdi: jami 126 suite + 1 alohida integration. Yangi CI Android build Java17/Java21 Yandex class format nomuvofiqligini ochdi; Java21 pin qilindi, yangi CI natijasi kutilmoqda.

- M020/M021/M030/M126 yopildi: himoyalangan sessiya, barcha qurilmadan chiqish va server profil/afzalliklari uchun regressionlar o‘tdi. Android login/restart amalda ko‘rildi. App `6d6ba2e` uchun Linux analyze/test va iOS simulator build CI muvaffaqiyatli; Windows 126 passed / 1 opt-in integration skipped. Real iPhone/signing tekshiruvi M120 ostida ochiq. Backend `9aa6179` va admin `3188515` CI muvaffaqiyatli.
- M010/M103: lokal Python 3.12.10 alohida papkaga o‘rnatildi, `.venv` va dependency install CI bilan moslandi. Pillow 13.0.0 yordamida haqiqiy PNG/JPEG/WebP decode, 3 MiB / 12 MP / 8192 px limit, animatsiyani rad etish va process boshiga 2 decoder cheklovi qo‘shildi. Buzilgan header/truncated/oversize rasmlar bo‘yicha 4 yangi test, cursor/ledger/auditni saqlash bilan jami 39 Python testi o‘tdi. Lokal bazada migration dry-run: yangi migratsiya yo‘q, integrity ok. Chek baytlari dalil sifatida o‘zgarmaydi; public media EXIF/object storage M104 ostida qoladi.

Har yangi yozuvda yechim, tekshiruv, qolgan cheklov va odatdagi yo‘ldan chetlanish qayd etiladi. Dastlabki 3–6 haftalik taxmin faol ishlab chiqish/test ko‘lamiga tegishli; SMS/MyID kelishuvi, Apple hisoblari va tashqi xizmatlarni kutish unga kirmaydi. Bu yakuniy reliz sanasi kafolati emas.

- M010/M126 yechimi: Windows Application log’da global Flutter 3.47.8 `flutter_tester.exe` 0xc0000005 bilan qulagani kuzatildi. Global SDK o‘zgartirilmadi; `.local/toolchains/flutter-3.44.5` CI bilan bir xil exact commitga o‘rnatildi, wrapper va lockfile qo‘shildi. Birinchi to‘liq Windows tekshiruvi 124 passed / 1 opt-in integration skipped; native crash takrorlanmadi. Git long filename xatosi SDK clone’iga lokal `core.longpaths=true` orqali hal qilindi. Python/Java/NDK va yangi wallet suite CI yakuni alohida tekshiriladi.
- M020/M120 dalili: Android emulatorda eski plaintext sessiyadan bir marta qayta kirish, keyin process force-stop/restartdan so‘ng secure-storage sessiya tiklanishi ko‘rildi. `cb1237a` iOS simulator build macOS CI’da muvaffaqiyatli (Runner.app); bu real iPhone Keychain/signing tekshiruvi emas. Linux full suite ham shu SHA’da o‘tdi.
- M030/M036: profil/til/notification/haftalik jadval uchun 7 mobil test o‘tdi. Server versiyasi bilan saqlanadi; xatoda lokal tanlov muvaffaqiyat sifatida almashtirilmaydi. Qidiruv/bron va yopiq sanalarga jadvalni ulash qolgan.
- M059–M065/M135–M139 qisman: versiyalangan QR va foiz, enaga balans ekrani, rozilik + chek, admin tushum tekshiruvi, atomar kredit va o‘zgarmas ledger qo‘shildi. Pul butun tiyinlarda; ikki admin parallel tasdiqlaganda bitta kredit. Bir chek/tushumning qayta ishlatilishi, summa mos kelmasligi, begona chek ID va qayta yuborish tekshirildi. Chek ro‘yxati rasmlarni birdan yuklamaydi; rasm ruxsat tekshirilgan alohida endpointdan ochiladi, navbat sahifalanadi. 33 Python / 4 admin / 2 wallet widget-unit testi o‘tdi. Qoralamani restartdan keyin tiklash, oluvchi rekvizitlari, aniqlashtirish va bildirishnoma, komissiya/bron bog‘lanishi qolgan; shu sabab keng vazifalar hali yopilmadi. Testlar sintetik, haqiqiy tushum yoki production balans o‘zgartirilmagan.
- M109/M110: uch repo draft PR’da; admin PR ham yaratildi va biriktirildi: https://github.com/umar200000/momiq_admin/pull/1 . Production main o‘zgarmagan. Server muhitini test-login holatidan xavfsiz o‘tkazish uchun SSH/staging konfiguratsiyasi aniqlashtirilmoqda; SMS kelishuvi yakuniy bosqichga qoldirilgan.

- M031 yopildi: account `_revision` qiymati bilan tranzaksion compare-and-increment qo‘shildi. Eski versiyadagi tahrir 409, versiyasiz eski mijoz 428 oladi; admin ham shu qoidaga amal qiladi. Forma ochilgandagi versiya saqlanadi, polling uni yangilab eski tahrirni yashirin tasdiqlamaydi. Ikki parallel yozishdan bittasi o‘tishi, admin konflikti va rollback API testlari; Flutter stale-form testi hamda 2 admin testi o‘tdi. Boshqacha yechim: maydonlarni avtomatik birlashtirish o‘rniga konservativ konflikt tanlandi; foydalanuvchi sahifani qayta ochib tahrirni takrorlaydi. Eski app/admin bilan yozish mos emas — stagingda mos versiyalar birga sinovdan o‘tadi.
- M021 amalga oshirildi, yakuniy UI/CI tekshiruvi davom etmoqda: sessiya 7 kun, jim refresh yo‘q; bir yoki barcha qurilmalardan chiqish, bloklanganda barcha client tokenlarini bekor qilish. Blokdan chiqarish tokenlarni qayta tiriltirmaydi. Barcha qurilmadan offline chiqish muvaffaqiyat sifatida ko‘rsatilmaydi; oddiy offline logout lokal ma’lumotni tozalaydi. Backendning 30 testi va Flutter sessiyasining 9 testi o‘tdi.
- M020 qisman: token OS secure storage ichidagi bitta muhit/API/user envelope’ga ko‘chdi; plaintext token ko‘chirilmay, bir marta qayta login talab qilinadi. Android backup/device-transfer yopildi, iOS device-only Keychain sozlandi. 4 vault regression testi o‘tdi; Android qurilma va iOS moslik tekshiruvi davom etmoqda. Rasmiy manba: https://pub.dev/packages/flutter_secure_storage .
- M100/M111 qisman: checksummed, tartibli tranzaksion migratsiya, SQLite WAL’ni qamragan backup va nusxada dry-run qo‘shildi. 4 test: eski yozuvni saqlash, idempotency, schema rollback, history rad etish va WAL backup. `.local/preview` bazasida dry-run: migration 1, integrity ok; original baza o‘zgarmadi. Hosted stop/backup/migrate/restart tartibi hali o‘rnatilmagan, shuning uchun vazifa to‘liq yopilmadi. API/upgrade tafsilotlari `API_CONTRACT.md`da.
- M120 davom etmoqda: macOS CI’da imzosiz iOS simulator build qo‘shildi; bu signing yoki real iPhone tekshiruvi bajarildi degani emas.
- M120 natija: `cb1237a` uchun macOS 15 / Flutter 3.44.5’da `Runner.app` simulator build muvaffaqiyatli yig‘ildi. Shu commitning Linux analyze/to‘liq testlari ham o‘tdi; Android debug build lokal yig‘ildi va emulatorga o‘rnatildi. iOS qurilma/Keychain/signing bosqichi ochiq.
- M025/M030/M036 davom etmoqda: noto‘g‘ri profil/notification JSON shakllari 500 o‘rniga 400 bilan rad etiladi; hayvon va manzil ixtiyoriy matnlari normallashtirildi, dublikat ID, bool koordinata va yosh/jins tekshiriladi. Enaga notification/til va haftalik jadvalini serverda saqlash ulandi, lokal mock qiymatlar remote profilni bosmaydi. Jadval timezone’i Asia/Tashkent, hafta Dushanbadan boshlanadi. Yopiq sanalar, qidiruv va bron bilan jadval bog‘lanishi hali ochiq. 31 backend testi o‘tdi; yangi mobil ssenariylar tekshirilmoqda.
- M126 aniqlashtirildi: Windows Application log’da `flutter_tester.exe` uchun takroriy `0xc0000005`, bir xil `0x35aaf0` offset qayd etildi. Bu test runner’ning native process crash’i; umumiy «test o‘tdi» deb yashirilmaydi. CI bilan bir xil Flutter 3.44.5 lokal alohida papkaga o‘rnatilib tekshirilmoqda; mavjud global Flutter 3.47.8 almashtirilmaydi.
- Admin uchun ham `codex/production-foundations` branch va draft PR ochildi: https://github.com/umar200000/momiq_admin/pull/1 (`1862c80`, CI muvaffaqiyatli). Backend/app bilan revision shartnomasi birga deploy qilinadi.

- Ish branchlari: tegishli repolarda `codex/production-foundations`; bu hali main yoki deploy emas.
- M013 yopildi: `seed_test_data.py` faqat yangi/belgilangan local/test bazani qabul qiladi; ishlab turgan noma’lum bazani o‘zlashtirmaydi. Idempotency, tozalashda begona yozuvlarni saqlash va bog‘liqlik bo‘lsa rad etish testlari o‘tdi.
- M026 yopildi: notes yo‘q/null/bo‘sh bo‘lganda ro‘yxat ham, tahrirlash sahifasi ham ochiladi; ism/yosh/zot/jins defaultlari tuzatildi. `customer_pet_optional_fields_test.dart`: 4 test o‘tdi.
- M008/M009/M019 davom etmoqda: runtime muhit validatsiyasi, bazaning muhit belgisi, production test-login taqiqi, mobil URL/health tekshiruvi va tokenning muhitga bog‘lanishi yozildi. Hosted staging hali yaratilmagan, productiondagi eski konfiguratsiya o‘zgartirilmagan.
- M011 yopildi: `start.ps1 -Port 8081 -Seed` va qayta ishga tushirish tekshirildi; admin papkasi, adb reverse va MapKit kalitini berish tartibi `LOCAL_DEVELOPMENT.md`da. Android debug APK yig‘ildi va emulatorda 8081 API bilan kirish, TEST enaga katalogi, hayvon ro‘yxati va ixtiyoriy maydonlari bo‘sh tahrirlash shakli ishladi. Haqiqiy xarita kaliti va iOS build tekshiruvi alohida ochiq vazifalarda qoladi.
- M012 qisman bajarildi: izolyatsiyalangan bazada 1 mijoz, 3 xizmatli enaga, hayvon va e’lonlar yaratildi. Buyurtma/chat/hisobot ssenariylari tegishli modellar bilan kengaytiriladi.
- Tekshiruv: `python -m unittest -q` — 23 test o‘tdi; backend GitHub CI ham o‘tdi (`9c32975`). Flutter analyze va to‘liq Linux CI testlari o‘tdi (`00b28e5`). Lokal API integration testi 8081 portda o‘tdi. Windows’da ayrim suite jarayonlari uzilishi qayd etildi; alohida processlar ham hammasini bartaraf etmadi, M126 Windows qismi ochiq.
- M015 yopildi: Git Credential Manager orqali yozish huquqli hisob tekshirildi, ikkala branch push qilindi va draft PR’lar ochildi. GitHub connector boshqa hisob bilan faqat o‘qiy oladi. Ikkala main branch hozir himoyalanmagan — M109 ochiq. PR’lar: https://github.com/umar200000/momiq_backend/pull/1 va https://github.com/umar200000/momiq_app/pull/1. Main merge/deploy bajarilmadi.

**Tekshirilgan boshlang‘ich holat**

- Profil, hisob sozlamalari, e’lon saqlash, mijoz/admin chatining asosiy API’lari mavjud. Buyurtma yaratish va bekor qilish hozir xato qaytaradi.
- E’lonlar va mijozlar katalogi alohida; nashr qilish zanjiri yo‘q. Internet katalogi audit paytida bo‘sh edi.
- Internet serveri HTTPS orqali ishlaydi, ammo test login yoqilgan va haqiqiy SMS ulanmagan. Emulatordagi joriy APK lokal API uchun yig‘ilgan.
- Backend/admin uchun main push avtomatik deploy qiladi. Test, aniq commitni deploy qilish va dastlabki rollback mavjud; ularni saqlab, to‘ldirish kerak.
- Backup shu serverda saqlanadi. Android release debug kaliti bilan imzolanadi, applicationId hali com.example.momiq_app.
- Backendning 14 testi o‘tdi. To‘liq Flutter test to‘plami yakuni tasdiqlanmagan. Emulatorda hayvonning notes maydoni yo‘q bo‘lsa sahifa yiqilishi qayta hosil qilindi.

**A. Ish boshlashdan oldingi mahsulot qarorlari**

- [ ] M001 — Tasdiqlangan reliz ko‘lamini bajarish: Android va iOS, Toshkent, uchala xizmat; tillar va aniq hudud chegarasi yakunlanadi, hududdan tashqaridagi bron rad etiladi, signing oxirida bajariladi.
- [ ] M002 — Uch xizmatning aniq qoidalarini tasdiqlash: hayvon turlari, sig‘im, uyga tashrif davomiyligi/soni, shaxsiy enaga eksklyuzivligi; UI va server bir xil qoidani qo‘llaydi.
- [ ] M003 — Har xizmat uchun enaga kiritadigan bir hayvon/bir kun tarifini bajarish: hayvonlar kunlik tariflari yig‘indisi × kunlar soni; shaxsiy enagada faqat 1 hayvon, alohida paket yoki qo‘shimcha hayvon chegirmasi taxmin qilinmaydi, kun chegarasi kelishiladi.
- [ ] M004 — Buyurtma holatlari va muddatlarini tasdiqlash: qabul/rad, javobsiz so‘rov, boshlash/yakunlash, bekor qilish, no-show, uzaytirish va nizo; har o‘tishning egasi belgilanadi.
- [ ] M005 — Tasdiqlangan hisob-kitob modelini bajarish: enaga balans to‘ldiradi, admin belgilaydigan komissiya (boshlang‘ich 10%) balansdan yechiladi, 15 000 so‘mdan past balansda yangi mijoz berilmaydi; yechish hodisasi/bazasi va qaytarish takliflari kelishiladi.
- [ ] M006 — MyID orqali tekshirish talabini saqlash: integratsiya kelishuv tugagach yakuniy bosqichda; tekshirish/moderatsiya alohida holatlar, testga haqiqiy MyID tasdig‘i berilmaydi.
- [ ] M007 — Ishlash mezonlari va xizmat xarajatlarini kelishish: kutilgan foydalanuvchi/so‘rov/video hajmi, tezlik, mavjudlik, backupdan tiklanish va support muddati; SMS/xarita/storage/to‘lov hisoblari va egalari belgilanadi.

**B. Muhitlar va takrorlanadigan ish jarayoni**

- [ ] M008 — Local, staging va production konfiguratsiyalarini ajratish: URL, baza, storage, push, SMS va payment kalitlari aralashmaydi; staging mavjudligi amalda tekshiriladi yoki yaratiladi.
- [ ] M009 — Development/test/production build sozlamalarini joriy etish: muhit belgisi ko‘rinadi; production build localhost, umumiy OTP yoki test provider bilan chiqarilmaydi.
- [ ] M010 — Flutter/Dart, Python, Java, Gradle, SDK va NDK versiyalarini uyg‘unlashtirish: yangi kompyuter va CI bir xil lockfile bilan build qiladi; mavjud lokal sozlama o‘zgarishlari alohida ko‘rib chiqiladi.
- [x] M011 — Mahalliy ishga tushirishni takrorlanadigan qilish: admin papka nomi, MapKit konfiguratsiyasi, emulator/telefon ulanishi hujjatlashtiriladi; yashirin qo‘lda tuzatish talab qilinmaydi.
- [ ] M012 — Test ma’lumotlarini boshqariladigan seed orqali yaratish: mijoz, enaga, xizmatlar, sanalar, hayvonlar, buyurtma holatlari, chat va hisobotlar; qayta ishga tushirish dublikat yaratmaydi.
- [x] M013 — Test ma’lumotlarini xavfsiz ajratish va tozalash: test identifikatori, alohida muhit yoki ko‘rinish cheklovi; tozalash faqat tegishli test yozuvlariga tegadi, real katalog/reyt­ing/hisob-kitobga ta’sir qilmaydi.
- [ ] M014 — SMS, push, media va QR/chek oqimi uchun sinov rejimlarini qo‘shish: test QR va belgilangan test chek/tushum, tasdiq/rad/qayta yuborish; real balans, real pul yoki tasodifiy telefonlarga ta’sir qilmaydi.
- [x] M015 — GitHub kirishi, repo huquqlari, branch va CI holatini tekshirish: foydalanuvchi login kerak bo‘lsa o‘zi bajaradi; ruxsatni tekshirish uchun main’ga sinov push qilinmaydi, tokenlar repoga/logga tushmaydi.

**C. Kirish va hisob hayoti**

SMS provayder bilan bog‘liq M016–M018 yakuniy bosqichga qoldirildi: provayder kelishuvi hali tugamagan. Hozir lokal test kirishi ishlatiladi; SMS integratsiyasi bajarilgan deb belgilanmaydi. M019 test kirishini productiondan ajratish himoyasi hozir ishlab chiqiladi, yakuniy reliz tekshiruvi SMS ulangach bajariladi.

- [ ] M016 — Haqiqiy SMS kodini so‘rashni ulash: telefon normallashtiriladi, challenge yaratiladi, provider natijasi va yuborish xatosi foydalanuvchiga to‘g‘ri ko‘rsatiladi.
- [ ] M017 — OTP tekshirishni server boshqarishi: kodning amal muddati, bir martalik ishlatilishi, urinish limiti va xavfsiz saqlanishi bor; noto‘g‘ri/eskirgan/qayta ishlatilgan kod rad etiladi.
- [ ] M018 — Qayta SMS yuborish va suiiste’mol cheklovlarini ulash: telefon/IP bo‘yicha limit, kutish vaqti va xarajat nazorati; ekrandagi taymer server holatiga mos keladi.
- [ ] M019 — Umumiy 111111 kodini production oqimidan chiqarish: test mexanizmi faqat belgilangan sinov muhitida ishlaydi; release va deploy tekshiruvi test login yoqilganini to‘sadi.
- [x] M020 — Tokenlarni platformaning himoyalangan xotirasiga ko‘chirish: eski SharedPreferences tokenini ko‘chirish/tozalash; backup, log va xato hisobotlari tokenni oshkor qilmaydi.
- [x] M021 — Sessiya muddatini va ko‘p qurilmali ishlashni yakunlash: yangilash yoki qayta kirish siyosati, bir/barcha sessiyadan chiqish, bloklanganda bekor qilish; offline logout ham lokal hisobni tozalaydi.
- [ ] M022 — Ro‘yxatdan o‘tishni davom ettirish va rol almashishni yakunlash: tugallanmagan profil qayta ochiladi, mijoz/enaga roli adashmaydi, rol tanlashning o‘zi ortiqcha huquq bermaydi.
- [ ] M023 — Telefon almashtirish va hisobni tiklash oqimini belgilash: egalik qayta tekshiriladi, dublikat hisob va raqam qayta berilishi holatlari boshqariladi, muhim o‘zgarish sessiyalarga ta’sir qiladi.
- [ ] M024 — Hisobni o‘chirishni ulash: ilova ichidagi so‘rov va tashqi veb yo‘li, qayta tasdiqlash, faol buyurtma/to‘lovlar siyosati, media/sessiya/push tokenlarini tozalash va zarur saqlash istisnolari foydalanuvchiga ko‘rsatiladi.

**D. Profil, hayvonlar va manzillar**

- [ ] M025 — Profil ma’lumotlarining yagona shaklini belgilash: majburiy/ixtiyoriy maydon, null/default, limit va xatolar; API qabul qilgan har bir haqiqiy yozuv ekranda ochiladi.
- [x] M026 — Hayvonlar sahifasidagi notes=null xatosini tuzatish: yo‘q izoh, yosh, zot va boshqa ixtiyoriy maydonlar xavfsiz ko‘rsatiladi; aynan topilgan holat regression test bilan yopiladi.
- [ ] M027 — Hayvon yaratish/tahrirlash/arxivlashni yakunlash: rasm, tur, yosh, jins, zot, izoh va Boshqa turi validatsiyasi bir xil; eski buyurtmadagi hayvon tarixi saqlanadi.
- [ ] M028 — Hayvon xavfsizligi ma’lumotlarini kelishilgan shaklda qo‘shish: emlash/pasport, allergiya, dori, xulq va favqulodda kontakt; faqat zarur tomonlar ko‘ra oladi, tibbiy qaror avtomatlashtirilmaydi.
- [ ] M029 — Manzil yaratish/tahrirlash/o‘chirishni yakunlash: koordinata, matn, kirish ko‘rsatmasi va xizmat hududi tekshiriladi; eski buyurtma manzili o‘zgarmaydi, aniq manzil ruxsatsiz ochilmaydi.
- [x] M030 — Profil, til va afzalliklarni qurilmalar o‘rtasida uyg‘unlashtirish: mock.profile/mock.notify kabi lokal nusxalar server haqiqatini bosmaydi; rasmni almashtirish/o‘chirish ham aks etadi.
- [x] M031 — Bir vaqtdagi tahrirlarni himoyalash: butun hisob JSON’ini yuborish bilan boshqa qurilma/admin o‘zgarishlari yo‘qolmaydi; versiya yoki qisman yangilash orqali konflikt aniqlanadi.

**E. Enaga xizmatini e’lon qilish**

- [ ] M032 — Enaga profili to‘liqligi va tasdiqlash talablarini qo‘llash: tajriba, tavsif, uy turi, rasmlar va tekshiruv holati kelishilgan mezonga mos bo‘lmasa nashrga o‘tmaydi.
- [ ] M033 — E’lon holatlarini joriy etish: draft, ko‘rib chiqilmoqda, tasdiqlangan, rad etilgan, to‘xtatilgan/arxivlangan; sabab va qayta yuborish foydalanuvchiga ko‘rinadi.
- [ ] M034 — listings va sitters katalogini yagona bog‘langan modelga keltirish: tasdiqlangan faol e’lon avtomatik qidiruvda paydo bo‘ladi; o‘chirilgan/bloklangan e’lon yo‘qoladi, dublikat bo‘lmaydi.
- [ ] M035 — Uch xizmat validatsiyasini birlashtirish: cat/dog/Boshqa mosligi, narx, manzil, sig‘im va shaxsiy enaga ziddiyatlari barcha kirish yo‘llarida tekshiriladi.
- [ ] M036 — Ish haftasi, vaqt oralig‘i, ta’til va yopiq sanalarni serverda saqlash: kalendar va qidiruv shu ma’lumotga tayanadi; timezone va tungi chegaralar kelishilgan qoidaga mos.
- [ ] M037 — E’lonni tahrirlash/to‘xtatish/arxivlash ta’sirini boshqarish: oldingi buyurtmaning narxi/manzili o‘zgarmaydi; faol majburiyatlar sig‘im yoki uy turi o‘zgarishidan buzilmaydi.
- [ ] M038 — MyID integratsiyasini yakuniy bosqichda bajarish: kelishuv/kalitlardan keyin callback, takroriy javob, rad/timeout, foydalanuvchiga bog‘lash va minimal hujjat saqlash tekshiriladi; hozir test chegarasi ajratiladi, integratsiya boshlanmaydi.
- [ ] M039 — Enaga bosh sahifasini haqiqiy ma’lumotga ulash: profil/e’lon holati, yangi so‘rov, yaqin buyurtma, bugungi parvarish va kerakli ogohlantirishlar; sun’iy raqamlar bo‘lmaydi.

**F. Qidiruv, xarita va tanlash**

- [ ] M040 — Katalogni sahifalab olish va serverda filtrlash: xizmat, hayvon turi, narx, sanalar, sig‘im va tekshiruv holati; tartiblash barqaror va natijalar takrorlanmaydi.
- [ ] M041 — Yaqinlik qidiruvini haqiqiy koordinatalarga ulash: masofa va xizmat radiusi serverda hisoblanadi; joylashuv berilmaganda tanlangan hudud bilan qidirish ishlaydi.
- [ ] M042 — MapKit va geokodlash sozlamalarini tugatish: muhit/ilova bilan cheklangan kalit, kvota va provider xatosi; kalit yo‘qligi sahifani yiqitmaydi.
- [ ] M043 — Joylashuv ruxsati rad etilishi, GPS o‘chiqligi va past aniqlikni boshqarish: majburlashsiz qo‘lda manzil tanlash, qayta urinish va sozlamaga o‘tish mavjud.
- [ ] M044 — Enaga tafsilotlarini real ma’lumot bilan to‘ldirish: xizmat narxi birligi, mavjud sanalar, tasdiq holati, haqiqiy rasmlar va sharhlar; aniq uy manzilini ochish siyosati bajariladi.
- [ ] M045 — Saqlanganlar va qidiruv holatlarini yakunlash: o‘chgan enaga, bo‘sh natija, yuklash/xato, sahifaga qaytish va filtrni tozalash; faol bo‘lmagan e’lonni bron qilib bo‘lmaydi.
- [ ] M046 — Soxta qiymatlar va uzilgan navigatsiyani tozalash: Oybek manzili/koordinatasi, sun’iy reyting/bo‘sh sana; enaga profilidan chat va buyurtmaga to‘g‘ri o‘tiladi.

**G. Buyurtmaning to‘liq hayot davri**

- [ ] M047 — Buyurtma modelini va ruxsatli holat o‘tishlarini yaratish: mijoz, enaga, e’lon, hayvonlar, sana/vaqt, manzil, narx va tarix bir-biriga bog‘langan.
- [ ] M048 — Xizmat jami summasini serverda hisoblash: tanlangan har hayvonning shu xizmatdagi kunlik tarifi × kunlar soni, so‘mda aniq hisob; 500 000 × 2 × 3 = 3 000 000 misoli test qilinadi, shaxsiy enagada 2 hayvon rad etiladi, mijoz xizmat puli Momiq orqali olinmaydi.
- [ ] M049 — Bron paytida mavjudlikni atomar tekshirish: parallel so‘rovlar bir joyni ikki marta band qilmaydi; shaxsiy enaga va uyga tashrif cheklovlari boshqa xizmatlar bilan ham hisoblanadi.
- [ ] M050 — To‘rt bosqichli buyurtma formasini ulash: hayvon, sana/manzil, pasport, yakuniy taklif; server tasdig‘isiz muvaffaqiyat ekrani ochilmaydi, xatoda kiritilganlar saqlanadi.
- [ ] M051 — Takroriy tasdiqlashni himoyalash: double-tap, timeoutdan keyingi retry va uzilgan aloqa bitta buyurtma yaratadi; natijani qayta tekshirish yo‘li bor.
- [ ] M052 — Enaga qabul/rad etishini ulash: javob muddati, sabab, buyurtma egasi huquqi va bandlik qayta tekshiruvi; ikkala tomondagi holat mos yangilanadi.
- [ ] M053 — Mijoz va enaga buyurtma ro‘yxati/tafsilotlarini ulash: kutilayotgan, faol, tarix, sahifalash va qidiruv; ruxsatsiz hisob buyurtmani ko‘rolmaydi.
- [ ] M054 — Kelishilgan bekor qilish siyosatini ulash: kim/qachon/sabab, komissiyani enaga balansiga qaytarish, sig‘im va bildirishnoma; takroriy so‘rov pulni ikki marta qaytarmaydi, mijozning xizmat puliga aralashilmaydi.
- [ ] M055 — Boshlash va yakunlashni ulash: hayvonni topshirish/qabul qilish tasdig‘i, vaqt chegaralari va rol huquqlari; nizoli holat avtomatik yakunlanmaydi.
- [ ] M056 — Javobsiz bron, vaqtinchalik rezerv va no-show holatlarini boshqarish: restartdan keyin ham muddatli ishlar davom etadi; tugagan so‘rov sig‘imni band qilib qolmaydi.
- [ ] M057 — Sana/hayvon/xizmat o‘zgarishi va uzaytirish siyosatini bajarish: qayta narxlash, mavjudlik va rozilik; imkon berilmasa aniq rad etiladi, yashirin tahrir bo‘lmaydi.
- [ ] M058 — Buyurtma tarixini o‘zgarmas snapshot bilan saqlash: xizmat/narx/manzil/hayvon ko‘rsatmalari va barcha holat o‘tishlari; keyingi profil tahriri eski kelishuvni o‘zgartirmaydi.

**H. Enaga balansi va platforma komissiyasi**

Momiq mijozning xizmat pulini yig‘maydi va enagaga xizmat daromadini payout qilmaydi. Birinchi reliz: Paynet Xolis QR, Momiq orqali chek yuborish, adminning chek+tushumni qo‘lda tekshirishi va balansni tasdiqlab to‘ldirishi. Ishlatilmagan qoldiq qaytarilmaydi; komissiyani qaytarish faqat ichki balansga tiklashdir. Click/Payme va avtomatik webhook ushbu reliz ko‘lamiga kirmaydi.

- [ ] M059 — Admin panelda Paynet Xolis QR kodini yuklash/almashtirish/faollashtirish: rasm va oluvchi ma’lumoti, ruxsatli rol, audit va versiya; enaga joriy QR’ni ko‘radi, eski so‘rovdagi QR nusxasi saqlanadi.
- [ ] M060 — Balans to‘ldirish so‘rovini yaratish: enaga QR orqali tashqi provayder ilovasida to‘laydi, Momiqdagi shu oqimda summa, vaqt/reference va chekni yuboradi; qoralama/ilovaga qaytish saqlanadi, so‘rov balansga avtomatik pul qo‘shmaydi.
- [x] M061 — Admin chek va haqiqiy tushumni solishtirib kreditlashi: oluvchi, summa, vaqt va tranzaksiya reference tekshiriladi; tasdiq, balans jurnali va so‘rov holati atomar yoziladi, ikki admin yoki retry ikki marta kredit qilmaydi.
- [ ] M062 — Chek so‘rovining qoralama, tekshirilmoqda, tasdiqlangan, rad etilgan va aniqlashtirish kerak holatlari: sabab, qayta yuborish, tarix va bildirishnoma; admin tasdig‘igacha sarflash mumkin balans o‘zgarmaydi.
- [ ] M063 — Komissiyani faqat ichki balansga qaytarish: tegishli buyurtmaga bog‘langan yozuv, summa chegarasi va idempotency; ishlatilmagan qoldiqni karta/naqdga chiqarish yo‘q, qoidani to‘ldirishdan oldin ko‘rsatish/rozilikni qayd etish.
- [ ] M064 — Komissiyani tasdiqlangan hodisada atomar yechish: buyurtma va balans birga yangilanadi, manfiy balans/dublikat yechish bo‘lmaydi; foiz va summa snapshot’i saqlanadi, xizmat daromadi payout’i qurilmaydi.
- [ ] M065 — O‘zgarmas balans jurnalini yaratish: admin tasdiqlagan tushum, komissiya, komissiya qaytimi va auditli tuzatish; chek so‘rovi/reference/admin/vaqt/sabab bog‘lanadi, jurnalni o‘chirish orqali qoldiq o‘zgarmaydi.
- [ ] M066 — Top-up va komissiya tafsiloti/kvitansiyasini ko‘rsatish: foydalanuvchi xizmat puli bilan adashtirmaydi; qoldiq qaytarilmasligi shartlarda yoziladi, platforma tushumi va fiskal/majburiy talablar mutaxassis bilan tekshiriladi.
- [ ] M134 — 15 000 so‘m qoidasini barcha yangi mijoz yo‘llariga ulash: qidiruv/tavsiya, eski link, favorites, yangi so‘rov/ilk chat va qabuldagi tekshiruv; mavjud buyurtma/chat/parvarish saqlanadi, to‘ldirganda mavjudlik qayta hisoblanadi.
- [ ] M135 — Admin panelda komissiya foizini boshqarish: default 10%, ruxsatli rol, 0–100 oralig‘i va kelishilgan aniqlik, tarix/sabab/kuchga kirish vaqti; yangi tarif eski so‘rov/buyurtma snapshot’ini o‘zgartirmaydi.
- [x] M136 — Enaga balans ekranini yaratish: qoldiq, Paynet Xolis QR, chek yuborish va tekshiruv holati, operatsiyalar, komissiya va 15 000 chegarasi; qoldiq qaytarilmasligi oldindan ko‘rinadi, pending chek pul sifatida ko‘rsatilmaydi.
- [ ] M137 — Balans va komissiya chegaralarini test qilish: 14 999/15 000/15 001 so‘m, komissiyadan kam qoldiq, parallel qabul, admin foizi o‘zgarishi, bekor/refund/reversal; ikki marta pul olish/qaytarish va tekshiruvni chetlash yo‘q.
- [ ] M138 — Chek/tushum dublikatini aniqlash: reference va oluvchi bo‘yicha bir tushum faqat bir hisobga kreditlanadi; ayni yoki o‘zgartirilgan rasmni qayta yuborish, boshqa enaga cheki, summa nomuvofiqligi va qalbaki chek admin tekshiruvidan chetlab o‘tmaydi.
- [ ] M139 — QR/chekdan mobil foydalanish va maxfiylikni tugatish: QR’ni kattalashtirish/saqlash, boshqa ilovaga o‘tib qaytish, kamera/galereyadan chek, format/hajm nazorati va upload retry; chek faqat egasi/ruxsatli admin uchun, media ommaga ochiq emas.

**I. Mijoz va enaga yozishmasi**

- [ ] M067 — Suhbatni ikki haqiqiy ishtirokchiga bog‘lash: mijoz/enaga identifikatori, xizmat/buyurtma konteksti; boshqa hisob ID’ni almashtirib xabar o‘qiy olmaydi.
- [ ] M068 — Suhbat boshlashni profil va buyurtmadan ulash: enaga tomonda chatlar ro‘yxati va javob berish ishlaydi; yozishma boshlash sharti mahsulot qoidasiga mos.
- [ ] M069 — Xabar yuborish, tartib, sahifalash va retry’ni tugatish: matn/rasm, yuborilmoqda/xato/qayta yuborish; vaqt yoki requestId kolliziyasi dublikat yaratmaydi.
- [ ] M070 — Xabarlarni samarali yangilash: delta/cursor yoki tanlangan realtime mexanizm, qayta ulanish va fondagi pollingni to‘xtatish; butun tarix har 3 soniyada yuklanmaydi.
- [ ] M071 — Yetkazildi/o‘qildi va o‘qilmagan sonini ulash: bir nechta qurilmada mos, eski xabar ochilishi yangi xabarni noto‘g‘ri o‘qilgan qilmaydi.
- [ ] M072 — Shikoyat, bloklash va moderatsiyani ulash: xabar/media bo‘yicha murojaat, spam limiti, dalil va moderator qarori; bloklangan tomon yangi bezovtalik yubora olmaydi.
- [ ] M073 — Admin aralashuvini aniq ajratish: javob muallifi foydalanuvchiga tushunarli, operator enaga bo‘lib yashirin ko‘rinmaydi; ko‘rish/javob/o‘chirish huquqi va audit mavjud.

**J. Parvarish va video hisobot**

- [ ] M074 — Kundalik parvarish sahifasini faol buyurtma va hayvonlarga ulash: enaga navigatsiyasidan ochiladi, mijoz ayni hisobotni ko‘radi; lokal namuna mustaqil haqiqat bo‘lmaydi.
- [ ] M075 — Ovqat, dori, sayr va boshqa ko‘rsatmalarni buyurtma bilan saqlash: har hayvon uchun jadval, mijoz ko‘rsatmasi va o‘zgarish tarixi; bo‘sh ko‘rsatma sahifani yiqitmaydi.
- [ ] M076 — Vazifa bajarilishini saqlash: vaqt, bajaruvchi, izoh va tuzatish tarixi; faqat tegishli enaga ruxsatli sana/holatda belgilaydi, boshqa qurilmada tiklanadi.
- [ ] M077 — Ertalab/kechki video qoidalarini bajarish: timezone, vaqt oynasi, davomiylik va kun almashishi; cheklov serverda tekshiriladi, telefon soatini o‘zgartirib chetlab o‘tilmaydi.
- [ ] M078 — Video yozish/tanlash/yuklash/ko‘rishni tugatish: progress, bekor qilish, retry, format/siqish, thumbnail va qayta ochish; yuklanmagan video yuborilgan deb hisoblanmaydi.
- [ ] M079 — Hisobot maxfiyligi va saqlash muddatini bajarish: faqat buyurtma tomonlari/ruxsatli operator, muddati cheklangan media havolasi, eski/lokal fayllarni reja asosida tozalash.
- [ ] M080 — O‘tkazib yuborilgan vazifa/video va favqulodda holatni boshqarish: eslatma, sabab, mijoz/supportga eskalatsiya; oddiy checklist real xizmat bajarilganining yolg‘on tasdig‘iga aylanmaydi.

**K. Bildirishnomalar**

- [ ] M081 — Qurilma push tokenini ro‘yxatdan o‘tkazish va yangilash: Android/iOS konfiguratsiyasi, ko‘p qurilma, logout va token eskirishi; xabar boshqa hisobga ketmaydi.
- [ ] M082 — Buyurtma, chat, parvarish, to‘lov va moderatsiya hodisalarini bildirishnomaga bog‘lash: qayta urinish va dublikatdan himoya; hodisa saqlanmasdan xabar yuborilmaydi.
- [ ] M083 — Bildirishnoma afzalliklari va ruxsatlarni uyg‘unlashtirish: mijoz/enaga sozlamalari serverda; OS ruxsati rad etilganda ilova ishlaydi, tranzaksion xabar qoidasi tushunarli.
- [ ] M084 — Bildirishnomadan tegishli sahifaga o‘tishni ulash: ilova ochiq/yopiq, login talab etilgan va obyekt o‘chgan holatlar; deep link ruxsat tekshiruvini chetlab o‘tmaydi.
- [ ] M085 — Ilova ichidagi bildirishnomalar tarixini va yuborish kuzatuvini qo‘shish: o‘qilgan holat, retry va provider xatosi; lock-screen matnida maxfiy manzil/hujjat ochilmaydi.

**L. Sharhlar, murojaatlar va ishonch**

- [ ] M086 — Sharh yozish huquqini haqiqiy tugallangan buyurtmaga bog‘lash: bir buyurtmaga belgilangan miqdor, reyting chegarasi, tahrir muddati; o‘ziga yoki bo‘lmagan buyurtmaga sharh yo‘q.
- [ ] M087 — Umumiy reyting va sharhlar ro‘yxatini serverdan ko‘rsatish: sahifalash, son/o‘rtacha hisob, moderatsiya/o‘chirishdan keyingi qayta hisob; mock sharh hisobga kirmaydi.
- [ ] M088 — Mijoz va enaga yordam murojaatini yagona ticket oqimiga ulash: mavzu, buyurtma, matn/media, javoblar va holat; yuborilgan murojaat qayta ochilganda ko‘rinadi.
- [ ] M089 — Nizo va takroriy holatlarni boshqarish: 30 kun ichida 3 ta kech bekor/tasdiqlangan kelmaslik admin ko‘rigiga, favqulodda vaziyat va yagona hodisa hisobi; kelmaslik nizosi 48 soatda ko‘riladi, xizmat boshlanmagan bo‘lsa komissiya balansga qaytadi, mijozning xizmat puli qaytarilmaydi.
- [ ] M090 — E’lon, profil, sharh va mediaga shikoyat/moderatsiya qo‘shish: sabab, ko‘rib chiqish, yashirish, apellyatsiya; qoidabuzarlik va operator harakati kuzatiladi.
- [ ] M091 — Foydalanish shartlari, maxfiylik, bekor qilish va hamjamiyat qoidalarini tayyorlash: biznes egasi tasdiqlaydi, versiya/rozilik qayd etiladi; shaxsiy ma’lumotlar va hududiy talablar mutaxassis bilan tekshiriladi.

**M. Boshqaruv va kundalik operatsiyalar**

- [ ] M092 — Operator rollari va minimal huquqlarni ajratish: support, moderatsiya, moliya, administrator; umumiy admin paroli o‘rniga shaxsiy hisoblar va muhim kirishlar uchun kuchli himoya.
- [ ] M093 — Foydalanuvchi/e’lon boshqaruvini tugatish: sahifalash, qidiruv, filtr, tekshirish, nashr/rad/to‘xtatish; sabab va holat egasiga ko‘rinadi.
- [ ] M094 — Buyurtma boshqaruvini ulash: holat tarixi, tomonlar, parvarish va nizo; operator qoidani chetlab o‘tadigan o‘zgarish qilsa alohida huquq va audit talab qilinadi.
- [ ] M095 — Cheklarni tekshirish uchun admin navbatini ulash: enaga/so‘rov/QR/reference/summa va tushumni solishtirish, tasdiq/rad/aniqlashtirish, ruxsatli kredit va audit; balansni sababsiz almashtirish yoki mijozning xizmat pulini boshqarish yo‘q.
- [ ] M096 — Support/moderatsiya ish navbatini yaratish: mas’ulga biriktirish, muddat, holat va javob; yopilgan murojaat tarixini yo‘qotmaydi.
- [ ] M097 — Audit jurnalini to‘liq qilish: kim, qachon, nima, sabab va o‘zgarish; maxfiy token/parol yozilmaydi, oddiy operator jurnalni tahrirlay olmaydi.
- [ ] M098 — Amaliy ko‘rsatkichlar va eksportni cheklangan huquq bilan berish: bronlar, muvaffaqiyatsiz to‘lovlar, ochiq nizolar, support muddati; keraksiz shaxsiy ma’lumot chiqmaydi.

**N. Ma’lumot yaxlitligi, media va xavfsizlik**

- [ ] M099 — Domen modeli va ma’lumot saqlash qarorini yakunlash: bog‘lanishlar, indekslar, unique cheklovlar, tranzaksiyalar; SQLite qolishi yoki PostgreSQLga ko‘chish parallel bron/yuklama natijasi bilan asoslanadi.
- [ ] M100 — Versiyalangan migratsiya va eski ma’lumotni ko‘chirishni joriy etish: backup, dry-run, idempotency va moslik; JSON/draft/demo yozuvlari real hisoblarni yo‘qotmasdan ko‘chadi.
- [ ] M101 — API shartnomasini hujjatlashtirish va tekshirish: request/response, status/xato kodi, null, pagination, vaqt va valyuta; eski ilova versiyasiga moslik siyosati mavjud.
- [ ] M102 — Har obyekt va amal bo‘yicha ruxsatni tekshirish: boshqa hisob, boshqa rol, bloklangan/o‘chgan hisob, o‘zgartirilgan ID va qo‘shimcha JSON maydoni orqali huquq oshmaydi.
- [ ] M103 — Barcha kirishlar va uploadni chegaralash: uzunlik, son, sana, koordinata, MIME/haqiqiy format, fayl/piksel/video hajmi; zararli yoki ortiqcha resurs talab qiluvchi fayl rad etiladi.
- [ ] M104 — Rasmlar/videolarni object storage’ga ko‘chirish: bazada metadata, thumbnail, maxfiy media uchun ruxsatli URL, EXIF maxfiyligi, yetim fayl tozalash; DB javobi Base64 bilan shishmaydi.
- [ ] M105 — Timeout, retry va background ishlarni ishonchli qilish: xavfsiz retry faqat mos amallarda, idempotency, rejalangan ishlarni deduplikatsiya va server restartidan keyingi davom ettirish.
- [ ] M106 — HTTPS, cookie, CSRF/origin, XSS va rate limit himoyalarini tekshirish: reverse proxy va real domenlarda sinov; admin va mijoz chegarasi saqlanadi, ishlamayotgan cheklov bordek hisoblanmaydi.
- [ ] M107 — Secret va bog‘liqliklarni boshqarish: Git/history/log skan, kalit rotatsiyasi, provider cheklovi, dependency/litsenziya tekshiruvi; secretlar CI/runtime orqali beriladi, lokal fayllar repoga kirmaydi.
- [ ] M108 — Shaxsiy ma’lumotlar hayot davrini tugatish: ko‘rish/eksport/o‘chirish huquqi, retention, rozilikni qaytarish, backupdan tiklaganda o‘chirilgan hisob qayta ochilmasligi; loglarda telefon/manzil/token niqoblanadi.

**O. Deploy, kuzatuv va tiklash**

- [ ] M109 — Mavjud CI/CD’ni real holati bilan tekshirish: main himoyasi, majburiy checks, cheklangan deploy kaliti, aniq SHA va concurrency; backend/admin versiyalari bir-biriga mos deploy qilinadi.
- [ ] M110 — Stagingdan productionga chiqarish tartibini belgilash: tekshirilgan commit/artifact, avtomatik deploy triggeri va muhit secretlari; yarim tayyor feature flag orqali yashiriladi yoki alohida branchda qoladi.
- [ ] M111 — Migratsiya/deploy ketma-ketligini xavfsiz qilish: eski-yangi kodning vaqtincha birga ishlashi, lock va backup; kod rollback’i sxemani o‘zi qaytarmasligi hisobga olinadi.
- [ ] M112 — Deploydan keyingi smoke tekshiruvini kengaytirish: health’dan tashqari DB, asosiy o‘qish, auth chegaralari va release SHA; test yozuvi kerak bo‘lsa izolyatsiyalangan va belgilangan bo‘ladi.
- [ ] M113 — Jarayon va infratuzilmani tekshirish: service restart, proxy timeout/body limit, firewall, HTTPS yangilanishi va filesystem huquqlari; nginx/systemd/bootstrap o‘zgarishi oddiy push bilan o‘rnatilmasligi hisobga olinadi.
- [ ] M114 — Alohida joydagi backupni sozlash: DB va media uchun shifrlash, retention, kirish cheklovi, backup yoshi/hajmi ogohlantirishi; shu server yo‘qolsa nusxa saqlanib qoladi.
- [ ] M115 — Tiklash va rollback mashqini bajarish: toza muhitda DB+media mos tiklanadi, belgilangan vaqt/yo‘qotish chegarasi o‘lchanadi; to‘lov va o‘chirilgan hisob holatlari qayta tekshiriladi.
- [ ] M116 — Monitoring va xato hisobotlarini ulash: uptime, xato ulushi, kechikish, disk/RAM/DB lock, navbat, SMS/payment/storage xatosi va mobil crash; mas’ulga amaliy signal keladi.
- [ ] M117 — Operatsion yo‘riqnoma va xarajat nazoratini tayyorlash: incident, provider uzilishi, kalit almashtirish, maintenance, disk/release/log tozalash, SMS/video limitlari; mas’ul va tiklash qadamlari aniq.

**P. Reliz sifati va tarqatish**

- [ ] M118 — Yakuniy applicationId/bundle ID va brend ma’lumotlarini o‘rnatish: com.example o‘rniga doimiy identifikator, ikonka, nom, versiya/build raqami va haqiqiy tavsif.
- [ ] M119 — Yakuniy bosqichda Android release signing va AAB tayyorlash: hozir signing o‘rnatilmaydi; oxirida debug signing almashtiriladi, kalitlar egaga tegishli va xavfsiz saqlanadi, release real qurilmada sinaladi.
- [ ] M120 — iOS relizini tayyorlash: hozir Mac/macOS CI orqali kod va simulator mosligi; signing/provisioning, APNs entitlement, archive va real iPhone/TestFlight tekshiruvi yakuniy bosqichda bajariladi.
- [ ] M121 — Nashr kunidagi store talablarini tekshirish: target API, native kutubxona mosligi, SDK privacy deklaratsiyalari, Data safety/App Privacy, account deletion, yosh reytingi va kontent moderatsiyasi.
- [ ] M122 — Store sahifasi va review materiallarini tayyorlash: haqiqiy screenshot/tavsif, support/privacy/delete URL, review uchun cheklangan kirish va test ko‘rsatmasi; mavjud bo‘lmagan imkoniyat reklama qilinmaydi.
- [ ] M123 — Uch tilda to‘liq UX tekshiruvi: tarjima, pul/sana/plural, xato matni, kichik ekran, katta shrift, screen reader, kontrast, klaviatura va ruxsat rad etilishi; sahifa/CTA yopilib qolmaydi.
- [ ] M124 — Yuklash/offline/xato holatlarini barcha asosiy oqimlarda yakunlash: forma yo‘qolmasligi, retry, session expired, sekin tarmoq, app background/restart; server tasdiqlamagan amal bajarildi deyilmaydi.
- [ ] M125 — Reliz artefaktlari va bosqichli tarqatishni sozlash: signed build CI artefakti, crash symbol/source map, versiya mosligi/minimal versiya, kichik pilot guruh va zarur bo‘lsa relizni to‘xtatish yo‘li.

**Q. Sinov va productionga chiqish dalillari**

- [x] M126 — Mavjud testlarni barqaror o‘tkazish: 14 backend testini saqlash, admin testlari va butun Flutter to‘plamini CI’da yakunlash; Windows runner uzilishining sababini ajratish, muvaffaqiyatli test soni qayd etiladi.
- [ ] M127 — Biznes qoidalari va API contract testlarini qo‘shish: narx, sana, sig‘im, holat o‘tishi, null, rol, xato javobi va eski ma’lumot; testlar faqat implementatsiyani takrorlamaydi.
- [ ] M128 — Ikki qurilma va admin bilan end-to-end oqim: ro‘yxat → enaga balansini to‘ldirish → e’lon/moderatsiya → qidiruv → bron → qabul/komissiya → chat → parvarish → yakun → sharh; xizmat puli Momiq orqali olinmaydi, restartdan keyin ma’lumot qoladi.
- [ ] M129 — Muqobil oqimlarni sinash: rad, timeout, bekor/refund, no-show, nizo, blok, hisob o‘chirish, telefon/rol almashish; hech biri begona ma’lumot yoki noto‘g‘ri balans qoldirmaydi.
- [ ] M130 — Parallel va nosozlik sinovlari: bir joyga ikki bron, chekni ikki admin tasdiqlashi, retry/dublikat chek, kredit yozilayotganida deploy/DB uzilishi, storage/SMS uzilishi; tiklanganda pul yoki majburiyat ikki marta yozilmaydi.
- [ ] M131 — Yuklama, maxfiylik va qurilma sinovlarini bajarish: M007 hajmi, eski/yangi Android, kelishilgan iOS, Wi-Fi/mobil/offline, katta media; ruxsatlar, API va dependency xavfsizlik tekshiruvi yakunlanadi.
- [ ] M132 — Pilot va chiqarish qarorini rasmiylashtirish: test hisoblari ajratilgan, muhim xatolar yopilgan, providerlar production rejimida, backup/monitoring/support ishlaydi; biznes egasi haqiqiy oqimni qabul qiladi.
- [ ] M133 — Hujjat va yakuniy auditni yangilash: README/API/deploy/operator ko‘rsatmalari amaldagi kodga mos, eski mock/placeholder/TODO inventari yopilgan; ma’lum cheklovlar, ochiq vazifalar va reliz dalillari yozilgan.

**Bajarish tartibi va bog‘liqliklar**

1. M001–M015: mahsulot qarorlari, muhitlar va test ma’lumotlari. Shu bosqichda hozirgi crash M026 ham yopiladi.
2. M020–M046 hamda M099–M108 zarur asoslari: sessiya, profil, e’lon, katalog va ma’lumot/ruxsat shartnomasi. SMS provayder ishlari M016–M018 yakuniy bosqichga qoldirildi; M019 production himoyasi hozirdan qo‘shiladi.
3. M047–M066 va M134–M139: bron, parallel bandlik, Paynet Xolis QR/chek, admin tekshiruvi/krediti, foiz va komissiya. Real QR/tushum rekvizitlarigacha belgilangan test ma’lumoti ishlatiladi; Click/Payme/webhook va mijoz xizmat puli payout’i qurilmaydi.
4. M067–M091: chat, parvarish, bildirishnoma, sharh va yordam. Har oqimda tegishli admin vazifalari M092–M098 ham tugallanadi.
5. M109–M125: deploy/tiklash, kuzatuv va Android/iOS relizi. SMS M016–M018, MyID M038 va signing M119–M120 yakuniy bosqichda. CI, monitoring, platforma mosligi va asosiy testlar ish boshidan tekshiriladi.
6. M126–M133: yig‘ma sinovlar, pilot va yakuniy chiqarish. Har oldingi bosqichda o‘z regression/integratsion testi bajariladi.

Tasdiqlangan qarorlar qayta so‘ralmaydi. Kun chegarasi/kunlik tashrif jadvali va aniq Toshkent poligoni kabi qiymati belgilanmagan qismlar alohida qayd etiladi. SMS, MyID va production signing oxirida bajariladi; test muhiti ularning haqiqiy bajarilganini da’vo qilmaydi.

**Productionga chiqarish mezonlari**

- Tanlangan reliz ko‘lamining barcha vazifalari dalil bilan yopilgan; shartli chiqarib tashlashlar yozilgan va tegishli interfeys yashirilgan.
- Haqiqiy mijoz va enaga asosiy xizmat oqimini boshidan oxirigacha bajaradi; test ma’lumoti yoki umumiy OTP production haqiqatining o‘rnini bosmaydi.
- Ruxsatsiz ma’lumot olish, ikki marta bron/to‘lov, ma’lumot yo‘qolishi va asosiy ekran crash’i kabi to‘siqlar ochiq emas.
- Buyurtma summasi, holati, mavjudlik va hisob-kitob server tomonidan tekshiriladi; qayta urinish xavfsiz.
- Backupdan tiklash, rollback, provider uzilishi va incidentga javob berish amalda sinalgan.
- Signed release real qurilmalarda, kelishilgan tillarda va tarmoq holatlarida tekshirilgan; store materiallari haqiqiy funksiyalarga mos.
- Kuzatuv, support va mas’ullar tayyor; pilot natijasiga ko‘ra ommaviy chiqarish qarori berilgan.

**Dalillar va rasmiy tekshiruv manbalari**

Mahalliy dalillar: [server.py](D:/projects/momiq_v1/momiq_backend/server.py), [deploy tartibi](D:/projects/momiq_v1/momiq_backend/DEPLOYMENT.md), [CI](D:/projects/momiq_v1/momiq_backend/.github/workflows/deploy.yml), [buyurtma holati](D:/projects/momiq_v1/momiq_app/lib/features/customer/data/customer_store.dart:321), [hayvon notes xatosi](D:/projects/momiq_v1/momiq_app/lib/features/customer/presentation/customer_account.dart:55), [release signing](D:/projects/momiq_v1/momiq_app/android/app/build.gradle.kts).

Android release uchun signing va AAB tayyorgarligi [Flutter rasmiy yo‘riqnomasiga](https://docs.flutter.dev/deployment/android) muvofiq tekshiriladi.

Hisob yaratadigan ilovada hisobni o‘chirish yo‘li mavjud bo‘lishi kerak; Google Play tashqi veb yo‘lini ham talab qiladi. [Google Play account deletion](https://support.google.com/googleplay/android-developer/answer/13327111?hl=en), [Apple account deletion](https://developer.apple.com/support/offering-account-deletion-in-your-app/).

Chat, rasm va sharh kabi foydalanuvchi kontenti uchun shikoyat, bloklash, moderatsiya va ochiq support aloqasi rejalashtirilgan. [Apple App Review Guidelines](https://developer.apple.com/app-store/review/guidelines/). Store talablari nashr oldidan qayta tekshiriladi.
