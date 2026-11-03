# Momiq store materiallari — qoralama

2026-10-29. M122 ichki tayyorgarligi. Bu fayl yoki `metadata.draft.json` store’ga yuborilmagan; nashrga tayyorlik belgisi emas. Ilova identifikatori `net.momiq.app`, ko‘rinadigan nomi Momiq. Signing foydalanuvchi qaroriga ko‘ra oxirida.

## Tayyor matnlar

`metadata.draft.json` uch tilda nom, qisqa tavsif, subtitle va to‘liq tavsifni saqlaydi. Matnlar tasdiqlangan Toshkent/it-mushuk/uch xizmat, enaga belgilaydigan kunlik tarif, har boshlangan 24 soat, xizmat pulini tomonlarning o‘zi kelishishi va QR/chek bilan komissiya balansini to‘ldirish qoidalariga mos.

MyID tekshiruvi, tashqi push, avtomatik Click/Payme, kafolatlangan xavfsizlik yoki to‘lov qaytimi reklama qilinmaydi. Birinchi reliz haqiqatda qabul qilinmaguncha ushbu qoralamani ommaga joylamang. Funksiya relizdan olib tashlansa, shu matndan ham olib tashlang.

Google Play nom 30, qisqa tavsif 80, to‘liq tavsif 4 000 belgi chegaralari [rasmiy listing yo‘riqnomasidan](https://support.google.com/googleplay/android-developer/answer/9859152?hl=en-EN) tekshirildi. Apple nom/subtitle 30 belgi chegarasi [App information](https://developer.apple.com/help/app-store-connect/reference/app-information/app-information) bilan tekshirildi. JSON’dagi uch nusxa ushbu limitlarga mos: subtitle 24/28/25, qisqa tavsif 68/67/69, to‘liq tavsif 1404/1289/1330 belgi (uz/en/ru). Nashr kuni qoidalar qayta tekshiriladi. `uz/en/ru` ichki matn kalitlari; App Store/Play Console qo‘llaydigan locale kodlari tekshirilgani degani emas.

## Haqiqiy screenshotlar navbati

| Kadr | Ko‘rsatiladigan haqiqiy ekran | Dalil sharti |
| --- | --- | --- |
| 1 | Uch xizmat va Toshkent katalogi | Faqat xizmatga mos it/mushuk; haqiqiy yaroqli listing holati. |
| 2 | Enaga profili, xizmat va narx | TEST tasdiqni MyID deb ko‘rsatmaslik; haqiqiy foydalanuvchi telefon/manzili yo‘q. |
| 3 | Hayvon va sana tanlovi, server hisoblagan jami | Enaga/hayvon/kun/umumiy narx bir-biriga mos; kadr uchun bron yaratish bloklangan testni chetlab o‘tmaydi. |
| 4 | Buyurtma holati va tomonlar suhbati | Faqat izolyatsiyalangan, ruxsatli QA hisoblar; boshqa hisob yozishmasi yo‘q. |
| 5 | Parvarish/video ro‘yxati | Haqiqiy yuklangan va o‘qish huquqi bor dalil; bo‘sh slotni yuborilgan deb bezamaslik. |
| 6 | Enaganing xizmat narxi va jadvali | Shu builddagi amaldagi forma; karta va ekran matni mos. |
| 7 | Yordam/shikoyat va sharh | Tugallangan haqiqiy QA oqimi; to‘qima reyting yoki foydalanuvchi tavsiyasi yo‘q. |

Har kadr uchun platforma, qurilma/o‘lcham, build/source SHA, til, ekran nomi va tekshiruvchi qayd etiladi. Android va iPhone ekranlari bir-birining o‘rniga qo‘yilmaydi. Captions uch tildagi haqiqiy UIga moslanadi; ekran maketi yoki AI rasmidan ishlayotgan funksiya dalili sifatida foydalanilmaydi. Joriy eski emulator yangilangan release build dalili emas. M055 va APK install bloklari ochilmaguncha tegishli kadrlarni olishga qayta urinilmaydi.

## Reviewer uchun yakuniy yo‘riqnoma tayyorlash tartibi

Hozir ishlaydigan reviewer credentials yoki bypass yo‘q va bu hujjatda maxfiy ma’lumot saqlanmaydi. Yakuniy kirish store’ning yopiq review maydonida beriladi; umumiy 111111 kodini production’da yoqish mumkin emas. SMS/MyID yakuniy integratsiyasi va ruxsatli review kirish tartibi tayyor bo‘lmaguncha submission bajarilmaydi. TEST seed hisoblari production katalogiga chiqmasligi sabab, mavjud lokal seed’ni review kirishi deb e’lon qilish mumkin emas.

Kirish tayyor bo‘lgach, tekshiruvchiga shu ketma-ketlik beriladi:

1. Belgilangan review hisobiga kirish, mijoz/enaga rejimlarini ko‘rish; haqiqiy mijoz hisobi ishlatilmaydi.
2. Toshkentdagi uch xizmatni ochish, it/mushuk va sana tanlovi, narxni ko‘rish.
3. Ruxsatli ajratilgan QA oqimida so‘rov/qabul/buyurtma tafsilotlarini ko‘rish; platforma komissiyasi va xizmat uchun tomonlararo to‘lov farqi tushuntiriladi.
4. Suhbat, parvarish hisoboti, yordam/shikoyat va yakunlangan buyurtma sharhini tekshirish.
5. Enaga uchun narx/jadval va balans tarixini ko‘rish. Reviewer haqiqiy pul yuborishga majbur qilinmaydi; ajratilgan tekshiruv ma’lumotlari biznes egasi tasdiqlagan rejimda tayyorlanishi kerak.
6. Kelishilgan hisob o‘chirish yo‘li va maxfiylik/support sahifalarini tekshirish.

Bu kelajakdagi review ssenariysi; ushbu amallar hozir bajarildi degan dalil emas. Store reviewer uchun yashirin admin huquqi yoki ishlab turgan foydalanuvchi ma’lumotiga ruxsat yaratilmaydi.

## Submission oldidan ochiq ma’lumotlar

| Kerakli ma’lumot | Hozirgi holat / bog‘liq band |
| --- | --- |
| Public support URL va kuzatiladigan email | Egasi/contact hali belgilanmagan; M117/M122. API domeni support URL o‘rnini bosmaydi. |
| Privacy va shartlar URL | Versiyalangan siyosat va egasi tasdig‘i kutiladi; M091/M108. |
| Hisob o‘chirishning public URL va ilova yo‘li | Faol buyurtma/dalil/backup siyosati bilan M024. |
| Store hisobi egasi va tashkilot ma’lumoti | Apple/Google hisoblarida tekshiriladi; repo ichida to‘qib qo‘yilmaydi. |
| Maxfiylik/Data safety/SDK deklaratsiyasi | Haqiqiy release binary va providerlar bo‘yicha M121; metadata JSON buni tasdiqlamaydi. |
| Haqiqiy screenshot va signed build | M119/M120/M125/M128/M131; signing oxirida, bloklangan testga tegilmaydi. |
| Reviewer kirishi va izolyatsiyalangan ssenariy | SMS/MyID va muhit qabulidan so‘ng; umumiy OTP/production TEST yorlig‘i bilan almashtirilmaydi. |
| Pilot va yakuniy chiqarish qarori | M132; egasining amaldagi oqim qabuli. |

`metadata.draft.json`dagi noma’lum URL/email maydonlari ataylab `null`; soxta manzil bilan to‘ldirilmaydi. Bu hujjat qabul qilinadigan store siyosati yoki yuridik moslik haqida kafolat bermaydi; maqsad mavjud dalillar va qolgan aniq ma’lumotlarni bir joyga yig‘ishdir.

2026-10-31. Mobil yordam formasida hisobni o‘chirish so‘rovi mavjud. Sinovchi “Hisobni o‘chirish so‘rovi” mavzusini tanlaydi, matnni kiritadi va tasdiq belgisini qo‘yadi. Kutilgan natija — egaga bog‘langan yordam murojaati. Haqiqiy hisobni o‘chirish, tashqi veb manzil va retention/backup bo‘yicha yakuniy siyosat ochiq. Store matnlaridagi delete/privacy URL qiymatlari egasi tasdiqlagach kiritiladi.

The deletion-request consent explains in Uzbek, English and Russian that the sitter’s unused prepaid balance is non-refundable on account deletion.
