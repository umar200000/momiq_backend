# Ikki yillik arxiv va tozalashdan oldingi tekshiruv

2026-11-12: egasi tasdiqlagan ikki yil uchun lokal texnik qism. Bu qonuniy saqlash muddati bo‘yicha xulosa emas. Avtomatik o‘chirish, fayllarni ko‘chirish, server timeri yoki zaxira nusxa yoqilmaydi.

## Ishlaydigan qism

Administrator panelida **Komissiya / QR → Audit va saqlash muddatlari**. Auditning asl yozuvlari faqat o‘qiladi. Yangi alohida baza/arxiv nusxasi yaratilmaydi. `UPDATE`, `DELETE`, `REPLACE` taqiqlari saqlangan; API’da ham yozish usullari 405 bilan rad etiladi. Support, finance va moderation bu bo‘limga kira olmaydi.

- `GET /api/admin/audit-archive?before=ID`: asl audit yozuvlari va saqlash holati. 50 tadan kamayuvchi ID bilan sahifalanadi.
- `GET /api/admin/retention-review?category=audit|topups|wallet|disputes|support|chatReports&before=ID`: faqat ID, hisob boshlanish sanasi, ko‘rib chiqish sanasi va ushlab turish sabablari. Chek, xabar, telefon, balans va surat bu hisobotga ko‘chirilmaydi.
- Har o‘qish auditga yoziladi. Audit yozish ishlamasa xususiy javob ham berilmaydi. Javobdan oldin tranzaksiya yopiladi.
- `retained`: ikki yil hali o‘tmagan. `held`: faol ish, yaroqsiz sana yoki katta tarixni alohida tekshirish kerak. `expired_review`: hisob bo‘yicha ikki yil o‘tgan; bu o‘chirishga ruxsat emas.
- Har bir javob `deletionEnabled=false`, har yozuv `deletionAllowed=false`. Client sana yoki o‘chirish parametrini yubora olmaydi. Hisobot sahifalari bir martalik eksport/snapshot emas; har so‘rov joriy holatni tekshiradi.

## Hisoblash qoidasi

Ikki **kalendar yil**, Asia/Tashkent (+05:00) vaqti. 29-fevral uchun ikki yildan keyingi 28-fevralning ayni vaqti olinadi. Aniq chegaragacha saqlanadi; chegaraning o‘zida `expired_review`. 730 kun bilan almashtirilmaydi.

| Toifa | Hozirgi texnik hisobning boshlanish nuqtasi |
| --- | --- |
| Audit | Asl hodisa vaqti. Bog‘liq moliyaviy/huquqiy istisnolar hali avtomatik aniqlanmaydi; o‘chirish yopiq. |
| Tushum/chek | Yaratish, yakuniy ko‘rib chiqish, tushum tarixi va kredit tuzatishlarining eng kech sanasi. Pending/needs_info ushlab turiladi. |
| Hamyon | Jurnal yozuvi va unga bog‘langan kredit tuzatishining eng kech sanasi. |
| Nizo | Yaratish, nizo yopilishi, bron yakuni va bron bilan bog‘langan keyingi yopilgan murojaatning eng kech sanasi. |
| Yordam murojaati | Yaratish/oxirgi yangilanish; bog‘liq bron yakuni, nizo yopilishi va keyingi yopilgan murojaat. Ochiq ish ushlab turiladi. |
| Chat shikoyati | Yaratish, ko‘rib chiqish va moderatsiya tarixi. Ochiq shikoyat ushlab turiladi. |

Tushum, hamyon va chat shikoyatlari uchun hisob egasining faol bron/ochiq nizolari hamda o‘zining yoki uning broniga bog‘langan ochiq murojaatlari konservativ tarzda ushlab turiladi. Yopilgan bron/nizo/murojaatning kechroq sanasi hisobni uzaytiradi. Bu aloqasiz yozuvni ham uzoqroq saqlashga olib kelishi mumkin; aniq huquqiy kategoriyalar tasdiqlanmaguncha avtomatik tozalash uchun ishlatilmaydi.

Yetishmayotgan, vaqt mintaqasiz, kelajakdagi yoki noto‘g‘ri sanalar ushlab turiladi. Bitta bog‘liq tarix 500 yozuvdan oshsa, u ham alohida ko‘rikka qoladi; so‘rov cheksiz tarixni xotiraga olmaydi. Bir sahifa 50 asosiy yozuvdan iborat.

## Hali bajarilmagan qism

- Majburiy saqlash istisnolari va aniq dalil bog‘lanishlari bo‘yicha yurist ko‘rigi.
- Ikki yildan keyin jismoniy o‘chirish tartibi: o‘zgarmas jurnal, hisob-kitob, referenslar va qayta yuborishni to‘suvchi yozuvlar bilan mosligi. Baza himoyasini olib tashlash amalga oshirilmagan.
- Serverda jadval, disk chegaralari va haqiqiy ma’lumot bilan qabul: serverga kirish kutiladi.
- M097/M108 ota bandlari shu sabab to‘liq yopilmaydi.

Video saqlashining oldingi 30 kun / nizo yopilgach 30 kun qoidasi o‘zgarishsiz. Hisoblarni o‘chirish, SMS/MyID/Firebase/xarita integratsiyalari, Telegram, operatsion backup va bloklangan jonli M055 testi bu ishga kirmaydi.
