# Egasi javoblari va yangi bajarish navbati — 2026-11-12

Bu qayd oldingi kutish sabablarini yangilaydi. Oldingi “hozir 0 kod vazifasi” xulosasi ushbu javoblardan OLDINGI auditga tegishli. Qaror qabul qilinishi texnik amalga oshirish yoki production qabuli bajarildi degani emas.

| Savol | Tasdiqlangan javob | Natija / qolgan ish |
| --- | --- | --- |
| 1 | Xato yashirilgan sharh/e’lonni qayta ochishga faqat administrator ruxsat beradi | Sharh restore va rejected/suspended e’lonni tasdiqlash server/UI’da admin bilan cheklanadi. Ommaviy matn/baho tahriri yo‘q. |
| 2 | Ikkinchi tasdiq (MFA) yo‘q | Egasi MFA talabini rad etdi; “keyin tanlanadi” emas. MFA bajarildi deb yopilmaydi. Parol, sessiya va ruxsat himoyalari saqlanadi. |
| 3 | Dastlab faqat egasi ishlaydi | Yangi xodim hisoblari kerak emas; mavjud hisoblarni o‘chirish topshirig‘i emas. |
| 4 | Audit 2 yil; faqat admin o‘qiydi; hech kim tahrirlamaydi | Baza UPDATE/DELETE/REPLACE himoyasi mavjud. Ikki yillik arxiv/expiry va server qabuli hali bajarilmagan. |
| 5 | Zarur moliya/nizo/shikoyat dalillari 2 yil, admin mas’ul | Barcha profil/video uchun umumiy 2 yil emas. Video uchun oldingi 30 kun/nizo yopilgach 30 kun saqlanadi. Dalillar kategoriyasi, muddat boshlanish nuqtasi va majburiy istisnolar huquqiy ko‘rikda yakunlanadi; avtomatik o‘chirish yoqilmadi. |
| 6 | Rekvizitlarni keyin admin kiritadi; ilk matnni yordamchi yozadi, yurist tekshiradi | Admin-only versiyali rekvizit/matn muharriri va 5 o‘zbekcha qoralama. Ommaviy nashr, tarjimalar, yurist tasdig‘i, consent va veb URL alohida ochiq. |
| 7 | Fiskal mas’ul — egasi | Mas’ul ma’lum; yozma fiskal xulosa hali taqdim etilmagan. |
| 8 | Ogohlantirish Telegram orqali egasiga | Keyingi javob: bot hali yo‘q. Bot va chat ulanishi kerak. Hali yetkazildi deb belgilanmaydi. |
| 9 | Dushanba–shanba 09:00–18:00, 3 ish kuni | Asia/Tashkent. Mobil yordam ekranida uch tilda ko‘rsatiladi. Kelmaslik nizosining maxsus 48 soati o‘zgarmaydi. Avtomatik SLA hisoblash/bayramlar qoidasi bu o‘zgarishga kirmaydi. |
| 10 | Airnet; GitHub CI/CD bor | Keyingi javob: panel manzili yoki sozlangan SSH ulanishini hozir bera olmaydi. Hosting ma’lum, vakolatli konsol kirishi mavjud emas. Deploy kaliti cheklanganligi o‘z kuchida. |
| 11 | Hozircha sinov muhiti local | Hosted staging hozir buyurtma qilinmaydi. Lokal natija hosted staging/deploy qabuli deb ko‘rsatilmaydi. |
| 12 | Oylik texnik budjet $200 | Xarajat yuqori chegarasi; hech qanday pulli xizmat avtomatik sotib olinmadi. |
| 13 | Video va cheklar VPSda; CDN va alohida backup yo‘q | Object-storage/CDN xaridi bekor. Hozirgi VPS private media himoyasi va disk nazorati tekshirilishi kerak. Cheklarning DB/Base64 hajmini boshqarish va kerak bo‘lsa VPS fayliga ko‘chirish talabi alohida qoladi. |
| 14 | Backup kerak emas | Offsite backup va unga bog‘liq restore mashqi egasi voz kechgan talablar. VPS yo‘qolganda tiklash kafolati yo‘q. Mavjud nusxalar o‘chirilmadi; deploy/migrationdagi himoya nusxalarini olib tashlash yoki jonli timerlarni o‘chirish bajarilmadi. |
| 15 | Hisoblar/kalitlar egasi faqat loyiha egasi | Qo‘shimcha recovery mas’uli yo‘q; mavjud himoyalar o‘chirilmaydi. |
| 16 | Firebase’ni egasi keyin ochadi | M014/M081–M085 provider va qurilma qabuli kutishda. |
| 17 | Xarita keyin | M042 kutishda. |
| 18 | SMS kelishuvi kutiladi | M016–M019 kutishda. Ishlayotgan server test kirishi saqlanadi. |
| 19 | Hisob MyID orqali tiklansin | M023 MyIDga bog‘landi; tayyor bo‘lmaguncha ishlaydi deb ko‘rsatilmaydi. |
| 20 | MyID kelishuvi kutiladi | M006/M038 kutishda. |
| 21 | Eski bazaning tozalangan nusxasi yo‘q | M100 eski ma’lumotli migratsiya qabuli ochiq. Sintetik migratsiya dalili mavjud, asl nusxa o‘rnini bosmaydi. |
| 22 | iPhone 13 Pro Max va Samsung Galaxy A52, aka/ustozniki | Modellar ma’lum; ulanish, OS versiyasi va amaliy sinov hali yo‘q. |
| 23 | Bloklangan test sababini ko‘rib chiqish | Oldingi qayd: live TEST bron/accept va APK install avtomatik approval tomonidan rad etilgan. Shu javob sinov o‘tdi degani emas; bu turn’da install/live M055 qayta bajarilmadi. |
| 24 | Do‘kon hisoblari ochilgan; domen olinadi | Hisoblarning kirish/egalik tafsiloti, domen, public support/privacy/delete URL kerak. Signing oxirida. |
| 25 | Pilot va yakuniy qabul mas’uli — egasi | Pilot qatnashchilari va haqiqiy oqim qabuli hali ochiq. |

## Ushbu javoblardan ochilgan aniq ishlar

- [x] D01 — 25 javobni qayd qilish; MFA, CDN/object storage va alohida backupdan voz kechishni “bajarildi”dan ajratish.
- [x] D02 — M090 sharh va cheklangan e’lonni qayta ko‘rsatish faqat administratorga tegishli; backend va UI regressiya testlari.
- [x] D03 — M091 admin-only rekvizit va 5 qoralama muharriri: yangi versiya, eski versiyani o‘zgartirmaslik, audit, stale konflikt, qoralamani saqlab qolish va matn ko‘rinishida preview. Schema 30.
- [x] D04 — M007/M117 support jadvalini mobil ekran va qoralamalarda uch tilda/tegishli matnda ko‘rsatish; umumiy 3 ish kuni maxsus 48 soatlik nizoni almashtirmaydi.
- [ ] D05 — M097/M108 ikki yillik audit/dalil retentionni kategoriyalar va saqlash boshlanish sanasi bilan amalga oshirish; majburiy saqlash istisnolarini yurist bilan tekshirish. Mavjud yozuvlarni hozir o‘chirmaslik.
- [ ] D06 — M116 Telegram bot/chat konfiguratsiyasi va amaliy signal; ulanish ma’lumoti kutiladi.
- [ ] D07 — M109/M111/M113 Airnet konsoli orqali deploy, TLS, xizmat va disk huquqlarini tekshirish; ulanish kutiladi.
- [ ] D08 — M104 VPSdagi video/chek saqlash va hajm boshqaruvi; offsite/CDN xaridisiz. Amaldagi server hajmi/yo‘li/limitlarini tekshirish kerak.
- [ ] D09 — M055 avvalgi blok shartini alohida ko‘rib chiqish; native/live test yopilmagan.

## Huquqiy qoralama chegarasi

`legal_drafts.json` mavjud mahsulot qoidalari va ushbu javoblardan yozildi. 2 yil egasining siyosati bo‘lib, barcha qonuniy saqlash majburiyatlari aynan 2 yil degan xulosa emas. Rekvizitlar ataylab bo‘sh; bo‘sh joyga tashkilot/STIR/manzil uydirilmagan. Qoralamalar ommaviy oferta yoki foydalanuvchi roziligi sifatida avtomatik nashr qilinmaydi. Yurist shu admin hisobida matnlarni tahrirlashi yoki egasiga tahrirni berishi mumkin; yangi alohida xodim hisobi ochilmadi.

Yurist uchun rasmiy manbalar: [Shaxsga doir ma’lumotlar to‘g‘risida, Lex.uz](https://www.lex.uz/uz/acts/-4396419?ONDATE=25.07.2026+00), [Elektron tijorat to‘g‘risida, Lex.uz](https://www.lex.uz/uz/acts/-6213382?ONDATE=25.07.2026+00). Majburiy retention, no-refund sharti, VPS joylashuvi va hisob o‘chirish istisnolari alohida tekshiriladi.

## Tekshiruv dalili

- Backend: yangi huquqiy hujjat/rol/migratsiya/readiness va API yo‘llarida 89 target test; keyin to‘liq `unittest discover` — 494 ta, 482 o‘tdi, 12 muhitga bog‘liq skip, 0 xato. Birinchi full run’da bitta eski restore testi schema 29 kutgan; schema 30 kutilishiga moslandi va butun suite qayta o‘tdi. Operatsion backup yoqilmadi; bu testlar vaqtinchalik bazalarda ishlaydi.
- Admin `64303e0457bec4f685e04e75d71eb9cd211c117d`: 120 Node testi, JS sintaksisi, secrets scan; [CI 43237484201](https://github.com/umar200000/momiq_admin/actions/runs/43237484201) muvaffaqiyatli, deploy skipped. Backend pin aynan shu nusxaga bog‘landi va release-pair tekshirildi.
- Mobil `f871d7850cacc1a5d7ccfe3cd9c5a02fbc7ddd6c`: 31 support widget/target/binding/resolution testi, Flutter analyzer — xato yo‘q. [CI 43237496298](https://github.com/umar200000/momiq_app/actions/runs/43237496298): `test` (131248665763) va `ios-simulator` (131248665336) muvaffaqiyatli; Android ARM64 va unsigned iOS QA paketlari yig‘ildi. Oxirgi tekshiruvda `ios-startup` (131255756684) hali ishlayapti, muvaffaqiyatli deb yopilmadi. Lokal widget/build natijasi haqiqiy telefon qabuli emas.
- Lokal `http://127.0.0.1:8081/admin/`: mavjud TEST bazada schema 30, autentifikatsiyalangan administrator orqali 5 qoralama va tarix GET tekshirildi. Rekvizitlar bo‘sh, uydirma tashkilot ma’lumoti yo‘q. UI yo‘li: **Komissiya / QR → Hujjatlar va rekvizitlar**.
- Backend draft PR’da main konflikti avvaldan bor, mergeable=false qayta tekshirildi. Yangi to‘liq backend GitHub CI/deploy bajarildi deyilmaydi; lokal to‘liq sinov dalili yuqorida. M019 test kirishi production serverida o‘zgartirilmadi.
