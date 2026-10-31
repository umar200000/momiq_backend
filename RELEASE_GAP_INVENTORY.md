# Relizdagi qolgan cheklovlar inventari

2026-10-29, `codex/production-foundations` manbasi. Bu production server/qurilma holatining tasdig‘i emas. Asosiy vazifa va qabul mezonlari [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md) da; bu hujjat topilgan markerlar nimani anglatishini va qaysi bandda hal bo‘lishini ko‘rsatadi.

| Topilma | Amaldagi holat va chegara | Qolgan ish |
| --- | --- | --- |
| `server.py` dagi `111111`, health’dagi `sms:false` | Bu lokal/izolyatsiyalangan test login. `config.py` production’da test loginni rad etadi; haqiqiy SMS yuborish yo‘q. | M016–M019: provayder kelishuvi, challenge/OTP, resend/abuse, haqiqiy hosted konfiguratsiya. Oxirida. |
| `myid_page.dart` dagi “MyID xizmati hali ulanmagan” | Haqiqiy tekshiruv muvaffaqiyati ko‘rsatilmaydi. `catalog.py` TEST tasdiqni haqiqiy MyID deb qabul qilmaydi; hozir production nashri/katalogi bu yo‘l bilan ochilmaydi. | M006/M038: kelishuv va kalitlardan keyin real integratsiya. Oxirida. |
| Bildirishnoma/sozlama ekranlaridagi “Push xabarlar hali ulanmagan” | In-app xabarlar, atomar o‘qish tasdig‘i/count snapshot, hodisa deduplikatsiyasi va sessiyaga bog‘langan navigatsiya mavjud. Eski `{ok:true}` serverda hisob yangilashgacha lokal taxmin qoladi. Bu Android/iOS tashqi push yetkazilganini anglatmaydi. | M081–M085: provider/OS token, yetkazish, APNs va haqiqiy deep-link/lifecycle qabuli. |
| `region=tashkent`, taxminiy katalog koordinatalari | Toshkent qidiruv hududi va maxfiylik uchun qo‘pol koordinata mavjud. Bu aniq shahar poligoni yoki tashqarida bronni rad etish kafolati emas. | M001/M029/M042: shahar chegarasini kelishish, geofence va xarita/geokodlash kalitlari. Toshkent ichida enaga radius cheklovi kiritilmaydi. |
| `mock.profile.*`, `mock.notify.*` | Test/preview uchun saqlangan eski lokal kalitlar. Profil va home’da API-enabled sessiya yo‘qligi mock profilni yashirin almashtirmaydi; yangi ro‘yxatdan o‘tish tuzatishida remote profil mock kalitlariga yozilmaydi. | M008/M009/M124: qolgan forma/login/lifecycle va hosted build qamrovi; M133: ishlatilmay qolgan compatibility kodini reja bilan tozalash. |
| `CustomerStore.book/cancel` va eski `CustomerOrders`/`CustomerCareReport` | Eski lokal bron yo‘li muvaffaqiyat yaratmaydi, aniq xato beradi. Hozirgi authenticated yo‘l `BookingInbox`/`BookingRequestPage`; server tasdig‘i, revision va idempotency ishlatiladi. API-enabled sessiyasiz customer store yuklanmaydi. | M133: legacy UI/compatibility chaqiruvlarini alohida migratsiya bilan chiqarish. Eski ekran matnini o‘chirish real bron oqimi tugadi degani emas; M055/M128 native qabul alohida qoladi. |
| Mavjudlikning eski lokal hisoblash fallback’i | Katalog kartasidan olib tashlandi. Faqat server bergan yaroqli `freeCapacity` ko‘rsatiladi, aks holda “tasdiqlanmagan”.0uyga tashrif joyi “bo‘sh” emas. | M123: qolgan ekranlarda uch til, real accessibility va qurilma qabuli. |
| Admin `input.placeholder` | Bu javob maydonidagi oddiy yordam matni; ulanmagan funksiya/TODO emas. `TODO`, `FIXME`, `mock` markerlari bo‘yicha JavaScript skani uni soxta bajarilmagan vazifaga aylantirmaydi. | M133: keyword skani bilan cheklanmay, marshrut/test/haqiqiy UI qamrovini tekshirish. |
| Base64 receipt/profile JSON va lokal video fayllari | Ruxsat, haqiqiy media validatsiyasi, video retention va private playback bor; barcha media uchun object-storage migratsiyasi tugamagan. | M104/M108/M114: storage joyi/credential/budjet, metadata/URL, retention va offsite restore siyosati. |
| E’lon/sharh qaroriga apellyatsiya | Egasi sabab bilan amaldagi qaror revision’iga murojaat qiladi; o‘zgarmas nusxa saqlanadi. Support javob beradi, faqat administrator yopadi. Schema27 da yopish amaldagi qaror fingerprinti bilan tekshiriladi va xabarga bog‘langan o‘zgarmas qaror nusxasi saqlanadi. Bu ko‘rinish qarorini avtomatik bekor qilmaydi. | M090: support kontent murojaatini audit bilan administrator navbatiga topshira oladi; private-media dalili/retention, nizo apellyatsiyasi va haqiqiy operator qabuli qoladi. |
| Mobil yordam tarixi va retry | API/ID/target/controller qayta bog‘langanda eski private holat ajratiladi; to‘liq page va revision tasdig‘i tekshiriladi, buzilgan javob asl tarix/qoralamani saqlaydi. | M101/M102/M124: native picker/process-death, haqiqiy hosted va operatsion qabul hali ochiq. Sessiya invalidatsiyasidan keyingi yashirish rebuild bilan bajariladi. |
| Chat va shikoyat sessiyasi/javobi | Manba almashtirish polling/editor/owned dialogni ajratadi; to‘liq page va ayni xabar/report tasdig‘i tekshiriladi. Blockdan oldingi poll yangi capability’ni bosmaydi; hisob eskirganda target almashtirish uni tiriltirmaydi. | M101/M102/M105/M123/M124: native lifecycle/picker va hosted qabul ochiq; allaqachon server qabul qilgan amal orqaga qaytarilmaydi. |
| Asosiy bron ro‘yxati/yaratish/tafsilot manbasi | API/sessiya, suhbat/e’lon/buyurtma va tashqi controller almashtirilishi private holatni ajratadi; owned dialoglar yopiladi, kech submit yangi sahifaga o‘tkazmaydi. Noaniq action clear va send parallel bajarilmaydi. | M101/M102/M105/M124: quote, inbox va request/accept/reject/cancel receipt tekshirildi. Qolgan endpointlarning moslik auditi, native lifecycle va hosted qabul hali ochiq. Bu bosqich jonli M055 sinovini bajarmaydi. |
| Buyurtma sharh/parvarish/nizo/video javoblari | API/buyurtma/controller manbasi va owned modal himoyasi bor. Review/care/dispute page, video overview va aniq write receipt, video/explanation POST tasdig‘i tekshirilgach retry tozalanadi; review/care/dispute format-buzilgan qoralamasi faqat aniq foydalanuvchi clear amali bilan tozalanadi; boshqa source natijasi yangi sahifani bosmaydi. | M101/M102/M105/M123/M124: native secure-storage/process-death/picker/playback va hosted qabul davom etadi. |
| Maxfiy rasmning kech javobi | Support/chat/hayvon rasmi va pasporti bitta hisob/manbaga bog‘langan o‘quvchi orqali ochiladi. Kech javob/xato boshqa manbani bosmaydi; widget qayta ishlatilganda oldingi rasm tozalanadi. | M102/M124: real qurilmadagi lifecycle/picker qabul sinovi. Bu screenshot taqiqi, allaqachon render qilingan pikselni rebuildsiz o‘chirish yoki object-storage migratsiyasi emas. |
| `deploy/` dagi Nginx/systemd/timer/bootstrap fayllari | Manbadagi tekshiruv va CI muvaffaqiyatli bo‘lishi ularni root-owned server konfiguratsiyasiga o‘rnatmaydi. Hozirgi kalit forced-deploy bilan cheklangan. | M008/M109–M117: imtiyozli bootstrap, staging, mos SHA juftligini promotion, offsite backup, tashqi monitoring va recovery mashqi. |
| `net.momiq.app`, unsigned build va eski emulator | Doimiy identifikator o‘rnatilgan; Android build va unsigned iOS simulator CI dalili mavjud. Eski emulatorni yangi APK ishlatyapti deb ko‘rsatish mumkin emas. | M119–M122/M125/M128/M131: signing, real qurilma, store materiallari va pilot. APK install/M055 bloklangan sinov qayta urinilmaydi. |
| Hisobni o‘chirish, telefonni almashtirish, fiskal/audit retention | Tasdiqlangan balans qoldig‘i qaytarilmasligi saqlanadi; hisob/aktiv majburiyat/dalil/backup bo‘yicha belgilanmagan siyosat o‘ylab topilmaydi. | M023/M024/M066/M091/M097/M108: yakuniy siyosat, egalik va mutaxassis/biznes egasi qabuli. |

Test seed/cleanup, vaqtinchalik fixture va provayder chegaralari: [TEST_DATA_BOUNDARIES.md](TEST_DATA_BOUNDARIES.md). M012/M014 ushbu inventar bilan to‘liq yopilmaydi.

## Dalil chegarasi

Manba skani `lib/**/*.dart`, runtime Python modullari va admin JavaScript’ida TODO/FIXME/mock/placeholder hamda “hali ulanmagan” markerlari, so‘ng tegishli chaqiruvlar va muhit guardlarini o‘qish orqali bajarildi. Test fixture’lari va oddiy HTML input placeholderlari mahsulotning tayyor bo‘lmagan imkoniyati deb sanalmadi. Dependency kataloglari, secret/runtime fayllari va foydalanuvchi ma’lumotlari bu inventarga ko‘chirilmadi.

Marker topilmagani funksiyaning to‘liq ishlashini isbotlamaydi. Bu inventar M133’ning bir ichki bosqichi; umumiy production/readiness yoki barcha61ochiq band tugagan degan xulosa emas. Har bir topilma yuqoridagi asosiy ID bilan kuzatiladi, yangi dublikat vazifa sanalmaydi.


## 2026-10-31 kuni ko‘rib chiqilgan 49 band

Jadval bosqich boshidagi 49 bandning mahalliy dalili va qolgan ishini ajratadi. Bajarilgan yangi qadamlar asosiy rejaning jurnalida belgilangan.

| Band | Tekshirilgan qism yoki amaldagi dalil | Yopish uchun qolgan ish |
| --- | --- | --- |
| M001 | Uch xizmat va har hayvonga kunlik narx bron javobida tekshiriladi. | Geofence mantiqi sintetik ko‘pburchak bilan tekshirildi. Haqiqiy Toshkent fayli va ikki platformada qabul ochiq. |
| M007 | Saqlangan enaga filtrining 200 ta juft lokal o‘lchovi bor. Yuklama vositasi mavjud instansga ulanmaydi. | Tezlik, mavjudlik, RPO/RTO va infratuzilma budjetini kelishish. |
| M008 | Muhit belgilari, bazaning muhiti hamda admin va runtime kataloglarining ajratilishi tekshirildi. | Egasi staging domeni, baza, storage va kirish usulini yakunda kelishishga qoldirdi. |
| M009 | Hosted build loopback taxalluslari va .invalid namuna domenini rad etadi. Production API porti 443. | Staging konfiguratsiyasi bilan haqiqiy build va hosted qabul. |
| M012 | Yopildi. Test bazasida uch holatdagi bron, sanalar, chat va parvarish hisoboti yaratildi. | Ikkinchi ishga tushirish yozuvlarni aynan saqladi. Mavjud bazaga o‘rnatish rad etildi. |
| M014 | Takror ishlatiladigan Paynet TEST bazasi, to‘lovsiz o‘qiladigan QR va offline push retry mavjud. | Tashqi push/provider sinov muhiti va qurilmadagi to‘liq sinov. |
| M019 | Yangi konfiguratsiya production test login’ni rad etadi. Amaldagi domen testLogin=true qaytardi. | Hosted konfiguratsiyani vakolatli rolloutda almashtirish. |
| M024 | Egasi ilovadan tasdiqlangan o‘chirish murojaati yuboradi. Takroriy jo‘natish tekshirildi. | Tashqi veb yo‘l, qayta autentifikatsiya va majburiyat/retention siyosatidan keyin haqiqiy o‘chirish. |
| M029 | Bron narx taklifi mijoz tanlagan sana va hayvonlarga bog‘lanadi. Saqlangan manzil va tarixiy snapshot qoidalari mavjud. | Aniq shahar chegarasi bilan yaratish/tahrirlash va chegara nuqtalari qabuli. Rasmiy [Kadastr geoportali](https://open.ngis.uz/) ko‘rib chiqildi. Reliz uchun tasdiqlangan sana va foydalanish shartlari bilan geometriya fayli hali tanlanmagan. |
| M042 | Map access va joylashuv xato holatlari mobil test to‘plamida. | Ilova va muhitga cheklangan kalit, provayder kvotasi hamda haqiqiy geokodlash. |
| M066 | Chek qancha summaga yuborilgani tasdiqlanadi. Tushum krediti qo‘lda tekshiriladi. | Kvitansiya va fiskal talablarni mutaxassis bilan tasdiqlash. |
| M139 | QR manbasi almashganda eski ko‘rinish yopiladi. Chek qoralamasi asl dalil bilan takrorlanadi. | Native kamera, galereya, provayder ilovasidan qaytish va real qurilmada qabul. |
| M078 | Xususiy playback/poster fayli uchun oddiy fayl, aniq katalog va link chegarasi tekshirildi. | Haqiqiy qurilmada tanlash, ijro, ruxsat va jarayon uzilishidan tiklash. |
| M081 | Sessiya va provider chegaralari inventarda. | Push loyihasi, token ro‘yxati/lifecycle, ikki hisob va ikki qurilmada delivery. |
| M082 | Bron, chat, parvarish, moliya va moderatsiya uchun tranzaksion ichki xabar sinovlari mavjud. | Tashqi yuborish navbati, retry va deduplikatsiyani provider bilan tasdiqlash. |
| M083 | Serverdagi afzalliklar va tranzaksion ichki tarix izohi mobil testlarda. | OS ruxsatlari va push sozlamalari birga sinalishi kerak. |
| M084 | Ichki xabardan manbaga o‘tish va sessiya invalidatsiyasi testlangan. | OS orqali fon/yopiq holatdan kirish, o‘chgan obyekt va login qabuli. |
| M085 | Ichki tarix, o‘qish tasdig‘i va sahifalash testlangan. | Provider yetkazish natijasi, retry va lock-screen maxfiyligi. |
| M090 | Ommaviy profil/uy rasmiga shikoyat ko‘rilgan rasmning slot va xeshiga bog‘landi. | Xususiy hisobot uchun aniq video va bron bilan shikoyat hamda admin ko‘rigi ulandi. Dalil saqlash siyosati, qolgan apellyatsiyalar va haqiqiy operator navbati qabuli ochiq. |
| M092 | Support, moliya, moderatsiya va administrator ruxsat testlari mavjud. | MFA, kirishni tiklash va haqiqiy shaxsiy operator hisoblari. |
| M097 | To‘lov qarorining takrori asl operator bilan bog‘landi. O‘qish va yozish auditi tekshirildi. | Audit saqlash muddati, arxiv kirishi va hosted nazorati. |
| M099 | SQLite DELETE/WAL moliya uzilishlari, qoldiq yarashtirishi va tanlangan enagalarni o‘qish tekshirildi. | Hosted parallel yuklamadan so‘ng DB tanlovini asoslash. |
| M100 | Tiklangan mustaqil bazaning muhiti va schema migratsiya checksumlari tekshirildi. | Eski hosted ma’lumotlar bilan migratsiya dry-run va qabul. |
| M101 | Quote, buyurtma, asosiy qarorlar, ro‘yxat, top-up va public-photo murojaati shartnomasi kengaydi. | Support receipt va hosted mobil capability tekshirildi. Qolgan endpointlar va tarixiy versiyalarning keng moslik auditi ochiq. |
| M102 | Eski hamyon sessiyasining kech javobi, begonaga tegishli tasdiq va source almashishi rad etiladi. | Barcha obyekt/rol kombinatsiyasi va yangi hosted build bo‘yicha qabul. |
| M103 | Noto‘g‘ri bron query, summa/dalil tasdig‘i, maxfiy media linklari va buzilgan javoblar tekshirildi. | Qolgan endpoint/upload qamrovi va haqiqiy proxy limitlari. |
| M104 | Lokal private media, lease bilan himoyalangan vaqtinchalik fayllar va yetim derivativlar haqiqiy process-exit bilan tekshirildi. | Object storage provayderi, bucket, kalitlar, migratsiya va yetim obyektlarni tozalash. |
| M105 | Noaniq chek takrori asl dalilni saqlaydi. Kredit va tuzatish process-exitdan keyin qayta tekshirildi. | Hosted worker/service restart va tashqi xizmat uzilishi qabuli. |
| M106 | Ochiq domenlarda anonim hisob/admin hamda begona origin o‘qishlari rad etildi. | Haqiqiy Nginx/Gunicorn va TLS bilan cookie/CSRF/rate-limit lokal Linux’da tekshirildi. Reliz domenida hosted qabul stagingdan keyin. |
| M107 | CI’da history va dependency skanlari, lock va litsenziya dalillari mavjud. | Kalit egasi va rotatsiya, provayder cheklovlari, native/asset litsenziyalari. |
| M108 | Hisob o‘chirish murojaati va tiklangan moliyaviy ma’lumot tekshiruvi mavjud. | Egasiga tegishli profil JSON eksporti va fayl tanlash oqimi tekshirildi. Qolgan toifadagi arxiv, haqiqiy o‘chirish, retention, rozilik va backupdan qayta ochilishni to‘sish ochiq. |
| M109 | Uch repo main holati read-only tekshirildi. Aniq admin commit bilan moslik tekshirildi. | Egasi faqat auditni qayd etishni tanladi. Qolgan qism root deploy skriptini o‘rnatish va hosted juftlikni tasdiqlash. |
| M110 | Draft PR va testlangan backend/admin juftligi mavjud. | Alohida stagingdan aynan sinovdan o‘tgan artefaktni productionga chiqarish. |
| M111 | Rollback oldingi kodning schema mosligini va qaytgandan keyin xizmat javobini tekshiradi. | Vakolatli serverda yangilangan deploy skripti bilan migration/rollback mashqi. |
| M112 | Preview’da yettita read-only smoke va baza yaxlitligi tekshirildi. | Yangi release SHA bilan haqiqiy domenlar orqali to‘liq smoke. |
| M113 | Uchta deploy/bootstrap skriptining har biri Bash sintaksis tekshiruvidan o‘tkaziladi. | Hostdagi systemd/nginx, firewall, TLS yangilanishi va filesystem huquqlari. |
| M114 | Tasdiqlangan nusxani age orqali shifrlash, buzilgan ciphertextni rad etish va offline restore sinaldi. | Alohida joydagi shifrlangan nusxa, kalit egasi, retention va signal. |
| M115 | Vaqtinchalik katalogga tiklash, media xeshi, hamyon va jurnal solishtiruvi sinaldi. | Haqiqiy offsite nusxa bilan RPO/RTO, o‘chirilgan hisoblar va operator mashqi. |
| M116 | Log kesimi uchun chegara ichida, oshgan va dalil yetishmaydigan holatlar CLI exit kodlari bilan ajratildi. | Monitoring manzili, alert egasi, mobil crash va real signal. |
| M117 | Tiklash, moliyaviy uzilish, threshold va rollback amallari operatsion yo‘riqnomada. | Mas’ullar, amaliy incident mashqi, xarajat va provayder limitlari. |
| M122 | Store review qoralamasida hisob o‘chirish murojaati sinov yo‘li yangilandi. | Haqiqiy screenshot, support/privacy/delete URL va review kirishi. |
| M123 | Yangi foto shikoyati va hisob so‘rovi uchun uch tilda matn bor. Rozilik izohi 320 × 640 ekranda 2× shrift bilan uch tilda accessibility daraxti va bosish orqali sinaldi. | Barcha ekranlarda real screen reader, kontrast, klaviatura va OS ruxsatlari. |
| M124 | Noto‘g‘ri tasdiq yoki eskirgan sessiya chek qoralamasini muvaffaqiyat deb o‘chirmaydi. | Haqiqiy offline, fon va qurilma restartidan keyingi to‘liq oqimlar. |
| M125 | QA paketidan o‘qilgan ID, versiya, build va minimal OS manifestga yoziladi. Android target SDK ham saqlanadi. | Release artefakti, symbol, minimal versiya va bosqichli pilot. |
| M128 | Alohida komponentlar fixture va CI’da ishlaydi. | Ikki qurilma va admin bilan bitta yakuniy E2E oqimi. |
| M129 | Rad, timeout, retry, begona hisob, qaror, no-show va komissiya holatlarida regressiyalar bor. | Real qurilmadagi muqobil oqimlar va siyosatga bog‘liq hisob amallari. |
| M130 | Haqiqiy child jarayon uzilganda top-up krediti va tuzatish takrorlanmasligi sinaldi. | Hosted deploy/DB, provider va storage uzilishi mashqi. |
| M131 | Izolyatsiyalangan HTTP yuklama, katalog, media va xavfsizlik testlari mavjud. | Kelishilgan Android/iOS qurilmalar matritsasi, mobil tarmoq va hosted yuklama sinovi. |
| M133 | API, deploy, operatsion, test chegaralari, store va ushbu 49 band dalillari yangilandi. | Pilotdan oldin ochiq bandlar, mock/placeholder inventari va yakuniy hujjat auditi. |
