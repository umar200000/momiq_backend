# Hozir bajariladigan ishlar — 2026-11-12

**So‘nggi tekshiruv:** iOS build/startup (birinchi ochilish va qayta ochilish) CI’da o‘tdi. D05a–D05c ikki yillik muddat hisoboti va faqat admin o‘qiydigan audit ko‘rinishi lokal tekshirildi. [Amaldagi bajarilgan qismlar va dalillar](OWNER_DECISIONS_2026-11-12.md), [retention chegarasi](RETENTION_REVIEW.md). Jismoniy tozalash/yurist/server qabuli yopilmagan.

**Yangi qarorlar bilan yangilandi:** egasi 25 savolga javob berdi. [Qarorlar va D01–D09 yangi navbat](OWNER_DECISIONS_2026-11-12.md) amaldagi keyingi ishlarni belgilaydi. Quyidagi 12/12 va “0 hozirgi kod vazifasi” shu javoblardan OLDINGI auditning yakunidir; yangi ochilgan ishlar yo‘q degani emas. MFA, offsite backup va object storage/CDNdan voz kechildi; ular tayyor deb belgilanmaydi.

Bu hujjat eski “37 joriy band” navbati o‘rniga ishlatiladi. 37 — production qabulining katta bandlari; quyidagi K raqamlar hozir tugatish mumkin bo‘lgan aniq kod vazifalari. 139 bandning tarixiy yopilish mezoni o‘zgarmaydi.

**Yakuniy hisob: 37 band = 7 lokal texnik qismi tayyor + 0 hozirgi kod vazifasi qolgan band + 30 keyinga qoldirilgan band. Aniqlangan 12 ta kod vazifasining 12 tasi bajarildi, 0 tasi ochiq.** Bu butun mahsulot productionga tayyor degani emas.

**Boshlang‘ich audit: 37 band = 5 lokal texnik qismi tayyor + 3 aniq kod ishi bor band + 29 keyingi shartni kutadigan band.** Uch kod bandi ichida **12 ta aniq vazifa** topildi. Qolgan test sonini vazifa soni sifatida sanamaymiz.

“Tayyor” — mavjud kod va lokal avtomatik tekshiruvlar bo‘yicha; haqiqiy qurilma/server/production qabuli degani emas. “Keyinga” — hozirgi ko‘rsatma bo‘yicha integratsiya, muhit, kirish, biznes qarori, signing yoki bloklangan sinovga bog‘liq qism. Bunda ilgari yozilgan kod bekor bo‘lmaydi. Barcha mavjud bo‘lishi mumkin bo‘lgan xatolar yo‘q degan kafolat berilmaydi: yangi tasdiqlangan nuqson bo‘lsa dalil bilan alohida qo‘shiladi, navbat jimgina kengaytirilmaydi.

## Aniq bajarish navbati

**Hozir ochiq: 0. Bajarilgan: 12.** Har vazifaning yopish sharti: bo‘sh/noto‘g‘ri tasdiq muvaffaqiyat hisoblanmaydi; obyekt, qaror va versiya qaytaradigan APIlarda ular yuborilgan so‘rovga solishtiriladi; qoralama yoki ayni retry saqlanadi; to‘g‘ri server javobi o‘tadi. O‘zgarish tegishli regressiya va server response-contract dalili bilan tekshiriladi.

| Holat | ID | Ota band | Aniq amal | API |
| --- | --- | --- | --- | --- |
| [x] | K01 | M102/M124 | Hisobni bloklash/blokdan chiqarish | `PUT users/{id}` |
| [x] | K02 | M102/M124 | Legacy xabarni o‘chirish | `DELETE messages/{id}` |
| [x] | K03 | M090/M124 | E’lon moderatsiyasi | `POST listings/{id}/{service}/review` |
| [x] | K04 | M124 | Komissiya va QR sozlamasi | `PUT platform-settings` |
| [x] | K05 | M124 | Tushumni tasdiqlash/rad/aniqlashtirish | `POST topups/{id}/review` |
| [x] | K06 | M124 | Balans kreditini tuzatish | `POST topups/{id}/corrections` |
| [x] | K07 | M090/M124 | Sharhni yashirish/ko‘rsatish | `POST reviews/{id}/moderate` |
| [x] | K08 | M090/M124 | Chat shikoyati qarori | `POST chat-reports/{id}/review` |
| [x] | K09 | M124 | Nizo qarori | `POST disputes/{id}/resolve` |
| [x] | K10 | M124 | Favqulodda holat istisnosi | `POST incidents/{id}/{user}/excuse` |
| [x] | K11 | M090/M124 | Ishni operatorga biriktirish | `POST work-queue/{kind}/{target}` |
| [x] | K12 | M090/M124 | Administratorga yo‘naltirish | `POST work-queue/support/{target}/escalate` |

## 37 bandning ajratilgan ro‘yxati

Har ID faqat bitta guruhda. K vazifalari tekshirib tugatildi. M102/M124 lokal texnik qismi tayyor guruhiga, M090 esa egasining qoldirilgan qarori sabab keyingi guruhga o‘tdi. Ota bandlarning production kataklari yopilmadi.

| Band | Guruh | Qolgan yakuniy shart | Mavjud dalil |
| --- | --- | --- | --- |
| M001 | Texnik qismi tayyor (lokal) | Uchala xizmatni Android va iOS qurilmalarida boshidan oxirigacha tekshirish. | Tasdiqlangan hudud bilan uchala xizmatda Toshkent va Chirchiq uchun narx olindi, Samarqand rad etildi. Vaqtinchalik bazada uchala xizmat uchun tungi bron, ish vaqtining tugash chegarasi va yopiq sanada boshlash qoidasi katalog va narx taklifi orqali solishtirildi. Production profilida jadval eski ilova yozuvlaridan keyin ham saqlanishi reliz sinovida tekshirildi. |
| M007 | Keyinga qoldirilgan | Hosted muhitda o‘lchash, tezlik, mavjudlik, RPO/RTO va infratuzilma budjetini kelishish. | Avvalgi juft o‘lchovda katalog p95 4,69 s dan 0,89 s ga tushdi. API qoidalariga mos yangi 167 e’lonli sinovda 1 000 hisob va 100 faol mijoz bilan p95 0,75 s, 5 829 so‘rov o‘tdi. |
| M009 | Keyinga qoldirilgan | Staging konfiguratsiyasi bilan haqiqiy build va hosted qabul. | Hosted build loopback taxalluslari va .invalid namuna domenini rad etadi. Production API porti 443. |
| M014 | Keyinga qoldirilgan | Firebase loyihasini egasi keyin ochadi. Provayder va haqiqiy qurilmadagi yetkazish sinovi qolgan. | Paynet TEST bazasi, sinov QR’i va tashqi push simulyatori tekshirildi. Bloklangan hisob va ovozsiz toifaga xabar yetkazilmaydi, avvalgi xabarlar qayta yuborilmaydi. |
| M024 | Keyinga qoldirilgan | Tashqi veb yo‘l, egasini qayta tasdiqlash, saqlash istisnolari va haqiqiy o‘chirish. | Ilovadan kelgan so‘rov faol bron yoki ochiq nizoda saqlanadi. Mijoz va enaga uchun shu murojaat majburiyat tugagach tekshiruvga o‘tadi. Support uning o‘rniga oddiy yopish amalini qo‘llay olmaydi. |
| M066 | Keyinga qoldirilgan | 4-noyabrda loyiha egasi yozma xulosa hozircha yo‘qligini bildirdi. Paynet Xolis orqali balans to‘ldirish va Momiq komissiyasi uchun chek talablari bo‘yicha mutaxassis xulosasi kutilmoqda. | 4-noyabrda balans yozuvlari va chekni o‘qish ruxsatlari bo‘yicha 4 ta backend testi, hamyon, tushum tarixi va chek bo‘yicha 14 ta Flutter testi o‘tdi. Ilova rozilik va chek talab qiladi. Tasdiq kutilayotgan so‘rovni takrorlash balansni oshirmaydi. |
| M078 | Keyinga qoldirilgan | Haqiqiy qurilmada tanlash, ijro, ruxsat va jarayon uzilishidan tiklash. | Mobil qoralamalar mustaqil tiklanadi; tasdiqlangan yuborishdan keyingi GET xatosi alohida ko‘rsatiladi va aynan o‘sha sana yangilanguncha yozish yopiq turadi. Xususiy playback/poster fayliga ruxsat fayl ochiladigan tranzaksiyada tekshiriladi. Bekor qilingan sessiya faylni olmadi. To‘liq va Range so‘rovida qisqargan playback fayli 503 qaytardi, asl fayl tiklangach ijro baytlari yana olindi. |
| M081 | Keyinga qoldirilgan | Push loyihasi, token ro‘yxati/lifecycle, ikki hisob va ikki qurilmada delivery. | Sessiya va provider chegaralari inventarda. |
| M082 | Keyinga qoldirilgan | Tashqi yuborish navbati, retry va deduplikatsiyani provider bilan tasdiqlash. | Bron, chat, parvarish, moliya va moderatsiya uchun tranzaksion ichki xabar sinovlari mavjud. |
| M083 | Keyinga qoldirilgan | OS ruxsatlari va push sozlamalari birga sinalishi kerak. | Serverdagi afzalliklar va tranzaksion ichki tarix izohi mobil testlarda. |
| M084 | Keyinga qoldirilgan | OS orqali fon/yopiq holatdan kirish, o‘chgan obyekt va login qabuli. | Ichki xabardan manbaga o‘tish va sessiya invalidatsiyasi testlangan. |
| M085 | Keyinga qoldirilgan | Provider yetkazish natijasi, retry va haqiqiy lock-screen qabuli. | O‘qish tasdig‘i asl ID, vaqt va umumiy hisobga bog‘langan. Sahifa ID lari qat’iy kamayishi tekshirildi. |
| M090 | Keyinga qoldirilgan | Aynan xeshga mos ommaviy surat operatorga ochilishi va almashtirilgani qaytmasligi Chrome orqali tekshirildi. Dalilni saqlash siyosati va haqiqiy operator navbatida qabul ochiq. Egasi yashirilgan sharhni qayta ko‘rsatishga kim ruxsat berishini keyingi muhokamaga qoldirdi. | Ommaviy rasm, sharh va xususiy video shikoyati manbaga bog‘langan. Yakunlangan nizo qarori bo‘yicha apellyatsiya, supportdan administratorga yo‘naltirish va aynan ko‘rilgan qarorga bog‘langan yozma javob tekshirildi. |
| M092 | Keyinga qoldirilgan | Egasi ikkinchi tasdiq usulini tanlashni keyinga qoldirdi. Usul, kirishni tiklash va shaxsiy operator hisoblari bilan qabul ochiq. | Support, moliya, moderatsiya va administrator ruxsat testlari mavjud. |
| M097 | Keyinga qoldirilgan | Saqlash muddati va arxivga kirish egasi tomonidan yakunga qoldirildi. Schema 29 himoyalarining reliz serveridagi nazorati kutilmoqda. | To‘lov qarorining takrori asl operatorga bog‘landi. Apellyatsiyani yopgan javob va nizo qarori auditda mos keldi. Haqiqiy Chrome ko‘rigi vaqtinchalik TEST bazada tekshirildi. Moliyaviy sozlamalarning oldingi va yangi versiyalari, o‘zgargan maydonlar va javob bir tranzaksiyaga bog‘landi. |
| M099 | Texnik qismi tayyor (lokal) | Bron moduli ishlaydigan Momiq serverida parallel yuklamadan so‘ng baza tanlovini asoslash. | 1 000 hisob va 10 ta joy uchun 100 parallel bron qabul qilish amali baza tranzaksiyalarida va ikki Gunicorn jarayoni orqali HTTP bilan tekshirildi. 10 ta komissiya yozildi, takroriy HTTP so‘rovlarida qoldiq o‘zgarmadi. |
| M102 | Texnik qismi tayyor (lokal) | Hamma obyekt va rol bo‘yicha hosted qabul hamda haqiqiy qurilmada sessiya almashishi. | Profil, eski yozishmalar, operator va enaganing top-up tafsilotida sessiya o‘qish tranzaksiyasida qayta tekshirildi. Noto‘g‘ri sessiya, boshqa qaror va takrorlangan credential rad etildi. 37 ta maxfiy o‘qish yo‘li sessiyasiz va yaroqsiz token bilan tekshirildi. Eski rol tugmasi va sessiya tiklanishidagi almashuv ikkala hisob uchun ham POST yubormadi. |
| M104 | Keyinga qoldirilgan | Egasi 4-noyabrda alohida saqlash joyi hali yo‘qligini tasdiqladi va tanlovni keyinga qoldirdi. Provayder tanlangach xususiy bucket, ko‘chirish va yetim obyektlarni tozalash tekshiriladi. | Lokal private media, lease bilan himoyalangan vaqtinchalik fayllar va yetim derivativlar haqiqiy process-exit bilan tekshirildi. |
| M105 | Texnik qismi tayyor (lokal) | Qolgan fon ishlarining hosted restartdan keyingi davom etishi va tashqi xizmat uzilishi qabuli. | Profil versiyasi, chek va kredit takrorlari tekshirildi. Operator javobi va xabarni o‘chirishda commit uzilgach takrorlash sinovdan o‘tdi. Chrome’da ikki operator bilan profil tahriri parallel blokni saqladi. Bir maydon o‘zgargan bo‘lsa 409 qaytdi va qoralama formada qoldi. Ketma-ket yoki parallel bir xil blok so‘rovlari har bir haqiqiy o‘zgarish uchun bittadan tarix yozdi. |
| M107 | Keyinga qoldirilgan | Kalitlar uchun mas’ullar, rotatsiya, Android/iOS kutubxonalari va tashqi provayderlar shartlari ochiq. | Egasi 16 ta rasm, 17 ta SVG va bitta Momiq ikonkasi loyiha uchun yordamchi orqali yaratilganini bildirib, ulardan foydalanishni tasdiqladi. 34 ta fayl repodagi nusxasi bilan solishtirildi. Quicksand va Baloo 2 litsenziyalari ilovadan ochiladi. |
| M108 | Keyinga qoldirilgan | Qolgan toifadagi arxiv, qayta autentifikatsiya, haqiqiy o‘chirish, saqlash muddati, rozilik va backupdan qayta ochilishni to‘sish. | Hisob egasining profil JSON eksporti productionga chiqarildi. Enaga faylida uning o‘z xizmat turlari va narxlari ham bor. Mobil nusxada manzil, profil, xizmat va hayvon obyektlaridagi noma’lum ichki maydonlar chiqarib tashlanadi. Ilova va admin panelining sinov versiyasida faol bron yoki nizo bilan o‘chirish navbati tekshirildi. |
| M109 | Keyinga qoldirilgan | Egasi umumiy deploy lock ichidagi nazoratni server konsolida tekshirishni keyinga qoldirdi. | Uch repo main holati qayd etildi. Backend CI admin f474aaa nusxasini sinaydi. Ikkala deploy jarayoni jonli admin fayllarini sinalgan versiya bilan solishtiradi. |
| M110 | Keyinga qoldirilgan | Alohida stagingdan aynan sinovdan o‘tgan artefaktni productionga chiqarish. | Draft PR va testlangan backend/admin juftligi mavjud. |
| M111 | Keyinga qoldirilgan | Vakolatli serverda yangilangan deploy skripti bilan migration/rollback mashqi. | Rollback oldingi kodning schema mosligini va qaytgandan keyin xizmat javobini tekshiradi. |
| M113 | Keyinga qoldirilgan | Egasi systemd/nginx, firewall, TLS yangilanish timeri va fayl huquqlarini server konsolida tekshirishni keyinga qoldirdi. | Ommaviy domenlarda HTTPS va yo‘naltirish tekshirildi. Host hisoboti Linux testlaridan o‘tdi. |
| M114 | Keyinga qoldirilgan | Asosiy serverdan alohida zaxira joyi hali yo‘q. Egasi tanlovni keyinga qoldirdi. Manzil tanlangach shifrlash kaliti, saqlash muddati, tashqi signal va haqiqiy tiklash tekshiriladi. | Nusxani shifrlash, alohida ulangan diskka uzatish, qayta o‘qish va dublikatsiz retry sintetik ma’lumot bilan tekshirildi. |
| M115 | Keyinga qoldirilgan | Haqiqiy offsite nusxa bilan RPO/RTO, o‘chirilgan hisoblar va operator mashqi. | Sinov diskidan qaytarilgan nusxada hamyonlar, tushum va bron komissiyalari yarashtirildi. Tiklashning vaqt chegarasi oshishi alohida exit kod beradi. |
| M117 | Keyinga qoldirilgan | Mas’ullar, amaliy incident mashqi, xarajat va provayder limitlari. | Tiklash va moliyaviy uzilish amallari yo‘riqnomada. Ovozli videolar bilan kuniga 200 hisobot ssenariysi uchun yuklash, saqlash va tomosha trafiki hisoblandi. [Hajm hisobi](OPERATIONS.md#video-hisobotlar-uchun-joy-va-trafik) |
| M122 | Keyinga qoldirilgan | Mahalliy sinov belgisi ko‘rinib turgan tasvir QA uchun saqlangan. Do‘kon uchun reliz tasvirlari, support/privacy/delete URL va review kirishi kerak. | Store review qoralamasida hisob o‘chirish murojaati sinov yo‘li yangilandi. iPhone 16 Pro simulatorining birinchi ochilish ekranida mijoz va enaga rollari tasdiqlandi. |
| M123 | Texnik qismi tayyor (lokal) | Barcha ekranlarda haqiqiy qurilmadagi screen reader, kontrast, klaviatura va OS ruxsatlari ochiq. | Foto shikoyati, rozilik izohi, katalog, profil va kirish xatolari uch tilda sinaldi. Katalog tugmalari hamda manzil formasidagi xaritada tanlash va saqlash 320 × 640 ekranda, 2× shrift bilan tekshirildi. |
| M124 | Texnik qismi tayyor (lokal) | Haqiqiy offline, fon va qurilma restartidan keyingi to‘liq oqimlar. | Noto‘g‘ri tasdiq yoki eskirgan sessiya chek qoralamasini o‘chirmaydi. Manzilni tahrirlashda hudud rad etilsa kiritilgan izoh formada qoladi. Eski profil jadval maydonini yubormaganida server avvalgi soatlarni saqlaydi. |
| M125 | Keyinga qoldirilgan | Reliz paketi, diagnostika symbol fayllari, foydalanuvchilarda minimal versiya va bosqichli pilot. | Android ARM64 va iOS simulator QA paketlarida ilova ID, versiya, build, minimal OS, native kutubxona va ikki shrift litsenziyasining xeshlari tekshirildi. |
| M128 | Keyinga qoldirilgan | Ikki qurilma va admin bilan bitta yakuniy E2E oqimi. | Alohida komponentlar fixture va CI’da ishlaydi. |
| M129 | Keyinga qoldirilgan | Real qurilmadagi muqobil oqimlar va siyosatga bog‘liq hisob amallari. | Rad, timeout, retry, begona hisob, qaror, no-show va komissiya holatlarida regressiyalar bor. |
| M130 | Texnik qismi tayyor (lokal) | Hosted deploy/DB, provider va storage uzilishi mashqi. | Lokal Linux’da Gunicorn ishchi jarayoni balans to‘ldirishda, bronni qabul qilishda va bekor qilishda uzildi. Ayni HTTP so‘rovini qaytarish har bir kredit, komissiya va qaytimni bir martadan yozdi. |
| M131 | Keyinga qoldirilgan | Haqiqiy Android/iOS qurilmalar matritsasi, mobil tarmoq va hosted yuklama sinovi. | Izolyatsiyalangan HTTP yuklama, katalog, media va xavfsizlik testlari bor. iPhone 16 Pro (iOS 18.6) simulatorida QA paketining birinchi ochilishi va jarayon yopilgach qayta ochilishi tasdiqlandi. [CI natijasi](https://github.com/umar200000/momiq_app/actions/runs/41190049621) |
| M139 | Keyinga qoldirilgan | Native kamera, galereya, provayder ilovasidan qaytish va real qurilmada qabul. | QR manbasi almashganda eski ko‘rinish yopiladi. Chek qoralamasi asl dalil bilan takrorlanadi. Enaga roli bekor bo‘lsa tushumlar ro‘yxati ochilmaydi. Chek va tarix javobini uzatish paytida ikkinchi ulanish bazaga yozishi tekshirildi. |

## Oldindan alohida qoldirilgan 17 band

M006, M008, M016, M017, M018, M019, M023, M038, M042, M055, M091, M100, M116, M119, M120, M121, M132. Ular yuqoridagi 37 ichida emas; o‘zgartirilmaydi.

| Bandlar | Keyinga qoldirilgan ish |
| --- | --- |
| M006, M038 | MyID kelishuvi va haqiqiy tekshiruv integratsiyasi |
| M008 | Alohida staging va muhit sozlamalari |
| M016–M019, M023 | SMS/OTP, test kirishni chiqarish, telefon almashtirish va hisobni tiklash |
| M042 | Xarita va manzil qidirish hisobi/kalitlari |
| M055 | Bloklangan boshlash/yakunlash native/live sinovi |
| M091 | Huquqiy matnlar va siyosatlar |
| M100 | Eski bazaning tozalangan sinov nusxasi bilan migratsiya |
| M116 | Monitoring xabarining mas’uli va kanali |
| M119–M121 | Android/iOS signing, do‘kon hisoblari va nashr qabuli |
| M132 | Pilot va reliz chiqarish qarori |

## Tekshiruv jurnali

Boshlang‘ich kod: mobil `0edc91b`, admin `d35d349`, backend reja `92971ee`. Avvalgi dalil: 865 Flutter, 96 Node, admin CI 43189504671. Ushbu sonlar hali yangi K vazifalari bajarildi degani emas.


### K01–K12 bajarildi — 2026-11-12

- Admin `ed5c47d53f0b8126d4f843cf3fa0542a10e365f7`: barcha 12 amal bitta API tekshiruviga ulandi. Transport yuborgan JSON nusxasi taqqoslanadi; kech o‘zgartirilgan forma tasdiqni almashtirmaydi. Xato javob qayta yuklash/muvaffaqiyat xabariga o‘tmaydi. Legacy xabar o‘chirish qayta yuborilganda asl sabab saqlanadi.
- To‘lov sozlamasida QR baytlari, oluvchi va komissiya; tushumda summa va reference; nizo/istisnoda obyekt, qaror va versiya; moderatsiyada tegishli holat tekshirildi. Mavjud `ok:true` javoblaridan qo‘shimcha identifikator kafolati chiqarilmadi.
- Admin to‘liq suite: **115 test, 0 xato**; barcha JS sintaksisi va `git diff --check` o‘tdi. Yangi testlar 12 amal, muqobil qarorlar, QR almashishi, ayni retry, keyin o‘zgargan assignment, kutilayotganda tahrirlangan forma va noaniq javobdan keyingi saqlangan qoralamani tekshiradi.
- `tool/check_admin_write_receipts.py`: **14 backend HTTP testi**, barcha 12 yo‘ldan **53 haqiqiy sintetik javob**, Node moslik tekshiruvi **20/20**. K01:2, K02:2, K03:1, K04:4, K05:7, K06:23, K07:1, K08:3, K09:1, K10:1, K11:5, K12:3. Faqat vaqtinchalik baza va loopback; ishlab turgan bazaga yozilmadi.
- Asosiy production hisobini kamaytirmadik: **139 = 85 to‘liq yopiq + 7 lokal texnik tayyor/yakuniy qabul ochiq + 30 keyingi shart kutuvchi + 17 oldindan alohida qoldirilgan**. Shu auditning aniq kod navbati tugadi. Integratsiya, bloklangan test, qurilma, staging, konsol va egasi qoldirgan qarorlar bajarildi deb belgilanmadi.
- [Admin CI 43199150091](https://github.com/umar200000/momiq_admin/actions/runs/43199150091): test job `131117697622` muvaffaqiyatli — 115 test, 0 xato; JS sintaksisi va secrets scan o‘tdi. Deploy skipped. Backend/admin juftligi yangi aniq SHA bilan tekshirildi, 4 release-pair testi o‘tdi. Ish branchlari push qilindi; production deploy hamda yangi backend to‘liq CI bajarildi deb ko‘rsatilmaydi.
