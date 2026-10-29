# Momiq operatsion yo‘riqnomasi

2026-10-29. M117/M116/M114/M115 ichki bosqichi. Bu hujjat repodagi vositalar bilan ishlash tartibi; ularning hosted serverga o‘rnatilgani yoki navbatchi/alert xizmati yoqilganini tasdiqlamaydi. Production chiqarish chegaralari [DEPLOYMENT.md](DEPLOYMENT.md) va [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md) da.

## Ish boshlashdan oldingi ma’lumotlar

Har hodisa uchun vaqtni UTC va zarur bo‘lsa Toshkent vaqti bilan, muhitni, oxirgi muvaffaqiyatli backend/admin SHA juftligini, kuzatilgan simptomni va oxirgi o‘zgarishni yozing. Ilova versiyasi/platformasi yordam beradi. Token, cookie, OTP, parol, to‘liq telefon/manzil, chek yoki video mazmunini issue/logga ko‘chirmang. Murojaat/buyurtma identifikatori ham faqat ruxsatli ichki yozuvda qolsin.

| Mas’uliyat | Hozirgi holat / tayinlash kerak bo‘lgan shaxs |
| --- | --- |
| Hodisa koordinatori va mijozga javob | Biznes egasi aniq operator va o‘rinbosarini belgilaydi; tashqi xabar avtomatik yuborilmaydi. |
| Server/root, TLS, rollout va recovery | Imtiyozli host operatori kerak; CI forced-deploy kaliti bu huquq o‘rnini bosmaydi. |
| Pul va tushum tekshiruvi | Shaxsiy finance/administrator hisobi; bank/provider tushumini ko‘ra oladigan mas’ul. |
| Xavfsizlik/moderatsiya/apellyatsiya | Support sabab/dalilni oladi, bo‘sh yoki o‘ziga biriktirilgan kontent murojaatini amaldagi muddat va auditli sabab bilan faol administratorga topshiradi; tegishli qarorni ruxsatli moderator yoki administrator beradi; apellyatsiyani faqat administrator yopadi. |
| Backup/offsite va monitoring | Storage/recovery kaliti egasi, navbatchi va alert manzili hali kelishiladi. |

SLO, javob berish jadvali, RPO/RTO, ogohlantirish chegaralari va xarajat budjeti tasdiqlanmagan. Ularni o‘ylab topilgan raqam bilan ishlayapti deb ko‘rsatmang. 48 soat — tasdiqlangan no-show nizosini ko‘rib chiqish muddati, barcha support murojaatlari uchun va’da emas.

## Dastlabki o‘qish tekshiruvi

Quyidagi Linux buyruqlari mos serverdagi ruxsatli operator uchun. Ular ushbu hujjat yozilayotganda serverda bajarilmadi. Environment faylini yoki credential saqlanadigan katalogni terminalga to‘liq chiqarmang.

```sh
sudo systemctl status momiq nginx --no-pager
sudo journalctl -u momiq -n 100 --no-pager
sudo systemctl list-timers certbot.timer momiq-backup.timer momiq-media-retention.timer momiq-backup-retention.timer
sudo df -h /var/lib/momiq /var/backups/momiq /opt/momiq
sudo df -i /var/lib/momiq /var/backups/momiq /opt/momiq
sudo du -sh /var/lib/momiq /var/backups/momiq /opt/momiq/releases
readlink -f /opt/momiq/current/backend
readlink -f /opt/momiq/current/admin
```

Logni ruxsatli terminalda ko‘ring; eski/proxy error loglari maxfiy bo‘lishi mumkin. Ulardan ommaviy nusxa tayyorlamang. `event=http` yozuvlarida faqat method/group/status/durationMs/outcome yig‘iladi. `database_busy` + 503 bazadagi lock kutishini bildiradi; generic 500 bilan aralashtirmang. Handler vaqti mijozga to‘liq yetkazish vaqti emas.

### Loglardan cheklangan diagnostika hisobotini olish

[tool/request_report.py](tool/request_report.py) mavjud log faylini faqat o‘qiydi yoki `-` bilan stdin qabul qiladi; JSON hisobot stdoutga chiqadi. Masalan, backend katalogida:

```sh
.venv/bin/python tool/request_report.py /operator-selected/http.jsonl
```

Systemd logi ishlatilsa operator avval vaqt oralig‘ini tanlaydi, `journalctl -o cat` bilan faqat message qismini oladi; default sana/PID prefiksli satrlar JSON sifatida qabul qilinmaydi. Vosita tarmoqqa ulanmaydi, database ochmaydi va alert yubormaydi. Fayl yo‘li yoki xato tafsiloti natijaga ko‘chirilmaydi.

Hisobot faqat oldindan ma’lum method/group/status/outcome qiymatlari va 0–86 400 000 ms davomiylikni oladi. Qo‘shimcha maydon, takroriy JSON kaliti, noma’lum label, noto‘g‘ri tur yoki maxfiy traceback bo‘lgan butun satr rad etiladi; `rejectedLines`ni doim tekshiring. Noto‘g‘ri yozuvlar yashirilgani uchun hisobotni barcha so‘rovlarning to‘liq sanog‘i deb qabul qilmang. 32 MiB, 100 000 satr yoki bir satrda 4096 baytdan oshsa qisman hisobot berilmaydi, exit 2 qaytadi. Bo‘sh/umuman yaroqsiz log ham exit 2; u sog‘lom tizim ko‘rsatkichi emas. Oldingi natijani almashtirmaslik uchun saqlashda yangi fayl nomidan foydalaning.

Umumiy va group bo‘yicha so‘rovlar, status/outcome/method soni, `nearest-rank` p50/p95/p99/max handler vaqti beriladi. O‘lchanmagan/null davomiylik alohida `missing`, eski outcome’siz yozuv `unspecified`, uzilgan javobning status 0 qiymati alohida sanaladi. p95 barcha loglar uchun emas, faqat qabul qilingan va vaqt o‘lchovi bor so‘rovlar uchun. Yozuvlarda vaqt belgisi yo‘q: vosita interval, requests/second, uptime, client latency yoki SLO buzilishini hisoblamaydi. Hosil bo‘lgan hisobot namuna doirasini ko‘rsatadi; tashqi monitoring/ogohlantirishni o‘rnatish M116’da hali ochiq.

[deployment_health.py](deployment_health.py) mavjud bazani read-only tekshiradi: muhit, migratsiya checksum va zarur jadvallar. Ishlayotgan release’ning o‘z runtime’i va amaldagi muhitini ishlating; `--mode production` yozish eski test serverni productionga aylantirmaydi.

```sh
/opt/momiq/current/backend/.venv/bin/python /opt/momiq/current/backend/deployment_health.py --data /var/lib/momiq --mode production
```

To‘liq tashqi smoke uchun [deploy_smoke.py](deploy_smoke.py) ga tasdiqlangan 40 belgili backend SHA va ikkala HTTPS origin beriladi. `--help` aniq argumentlarni ko‘rsatadi. Smoke GET-only: login, pul, bron yoki seed yaratmaydi. Production/staging promotion’da test-login yoki noto‘g‘ri SHA — rad etish sababi; guardni bo‘shatib o‘tkazmang.

## Hodisa bo‘yicha qaror

| Simptom | Tekshirish va keyingi amal | Muvaffaqiyat dalili |
| --- | --- | --- |
| 502/503, server qayta-qayta ochilib yopiladi | Process holati, disk/inode, oxirgi release va sozlama o‘zgarishini solishtiring. `database_busy` bo‘lsa writer davomiyligi/parallel ishlarni tekshiring. Restartdan oldin sabab va dalilni yozing; doimiy restart sikli bilan xatoni yashirmang. | Ready, mos SHA, to‘liq smoke, xato ulushi qayta me’yorga kelgani; restartning o‘zi yetarli emas. |
| Yangi release’dan keyin startup xatosi | Muhit/test-login guardi, admin release juftligi, migratsiya checksum va kerakli installed unitlarni tekshiring. Draft kodni main’ga yuborish root-owned skriptlarni o‘rnatmaydi. | Mos konfiguratsiya va compatible pair; kerakli bootstrap alohida tasdiqlangan. |
| Chek/top-up yoki komissiya natijasi noaniq | Asl requestId, ticket/top-up holati va ledger tarixini ruxsatli panelda solishtiring. Tarmoq javobi yo‘qolishi operatsiya bajarilmagan degani emas. Ayni payload/id retry’dan foydalaning. Tushumni tekshirmasdan yangi kredit yozmang. | Bitta tushumga bitta kredit; qoldiq va source-linked jurnal mos, auditda sabab/operator bor. |
| Admin ortiqcha kredit yozgan | Tasdiqlangan tuzatish oqimi: asl tushumga bog‘lash, sabab, audit; yetarli qoldiq bo‘lmasa rad etiladi va alohida ko‘rib chiqiladi. | Manfiy balans yo‘q, asl yozuv o‘chirilmagan, tuzatish alohida qayd etilgan. |
| Video upload timeout yoki playback yo‘q | Buyurtma ishtirokchisi/holati, hisobot metadata va retentionni tekshiring; server tasdig‘isiz yuborildi demang. FFmpeg/ffprobe, disk, processing logi va proxy vaqtini tekshiring. | Tegishli qatnashchi ruxsatli videoni ko‘ra oladi; boshqalarga ochilmaydi. Muddati tugagan faylni tiklab ochish yechim emas. |
| Xarita/provider xatosi | Kalit muhit/app cheklovi, kvota va provider holatini mas’ul bilan tekshiring. Kalitni logga chiqarmang; foydalanuvchi xatosiz retry/izoh ko‘rishi kerak. | Mos native qurilmada provider qabuli. Kalit bo‘lmasa bu qism hali ochiq. |
| SMS/MyID/push ishlamaydi degan murojaat | Hozir ular integratsiya qilinmaganini va in-app tarix tashqi pushdan farq qilishini tekshiring. MyID/SMS oxiriga qoldirilgan. | Test OTP yoki TEST belgisi haqiqiy verification sifatida ishlatilmagan. |
| Shaxsiy ma’lumot ochilishi gumoni | Ta’sirlangan yo‘l/rol/muhitni qayd eting, ruxsatsiz kirishni cheklashni vakolatli administrator bilan bajaring, auditni saqlang. Begona hisob bilan live sinash yoki ma’lumotni issue’ga chiqarish shart emas. | Kirish chegarasi tekshirilgan, sabab tuzatilgan va tegishli credential/recovery mas’uli qarori qayd etilgan. |

Mijozning enagaga to‘lagan xizmat pulini Momiq qaytarmaydi. Balans qoldig‘i chiqarilmaydi. Komissiya qaytimi tasdiqlangan bron/nizo qoidasi bilan balansga yoziladi; qo‘lda SQL o‘zgartirish yoki ledger tarixini o‘chirish operatsion yechim emas.

No-show nizosi 48 soatda ko‘rib chiqiladi; xizmat boshlanmagani tasdiqlansa komissiya qaytariladi. 30 kunda 3 ta distinct kech bekor qilish/tasdiqlangan kelmaslik administrator ko‘rigiga chiqadi; favqulodda holat hisobga olinadi. Avtomatik jarima yoki o‘ylab topilgan xizmat refundi qo‘shilmaydi.

## Backup, disk va tiklash

- Kundalik `momiq-backup.service` muvaffaqiyatli tugashi, yangi bundle va tekshiruv natijasini ko‘ring. Timer mavjudligi backup tayyor degani emas. `/var/backups/momiq` shu serverda: server yo‘qolishiga qarshi offsite himoya hali yo‘q.
- [backup_bundle.py](backup_bundle.py) `--verify` bilan tanlangan bundle’ning DB/media/manifestini tekshiradi. Nusxani yaratish `--data-dir` va yangi `--destination` bilan; mavjud nusxa bosilmaydi. Faqat ishlayotgan SQLite asosiy faylini ko‘chirish WAL-safe backup emas.
- Video retention: faol parvarish/ochiq nizo saqlanadi; tugash yoki nizo yopilishining keyingi vaqtidan 30 kun. Managed backup maksimal 14 kun yoki ichidagi video muddati tugaguncha saqlanadi. Retentionni disk uchun uzaytirmang yoki qo‘lda evidence faylini o‘chirmang.
- Disk/inode yetishmasa avval qaysi katalog o‘sganini aniqlang. Verified managed bundle pruning bor; unknown/custom backup, faol release, WAL, audit, ledger yoki media fayllarini umumiy recursive delete bilan tozalamang. Release/log cleanup siyosati alohida kelishiladi. Disk yetishmasligini to‘g‘rilash backupning tekshiruvini bekor qilmaydi.
- Tiklash yangi, to‘xtatilgan alohida instance’da boshlanadi; bir xil DB+media bundle tekshiriladi. Hozirgi bazaning ustiga snapshotni avtomatik yozmang. Snapshotdan keyingi pul/bron/o‘chirish hodisalari uchun yarashtirish qarori zarur.
- Recovery mashqida boshlash/tugash vaqtini, backup yoshini, integrity/FK/media holatini, hisob/session/pul/aktiv majburiyat/retention natijasini yozing. M055 live bloklangan ssenariy va APK install’ni shu nom bilan aylanib o‘tmang. RPO/RTO va offsite qabul hali o‘lchanib tasdiqlanmagan.

## Rollback va xizmatni qayta ochish

Eski release’ning o‘z `deployment_health.py`si joriy bazani o‘qib qabul qilmaguncha code rollback yo‘q. Checker yo‘q yoki schema mos emas bo‘lsa avtomatik qaytarish to‘xtaydi; DB downgrade qilinmaydi. [predeploy_backup.py](predeploy_backup.py) nusxasi keyingi yozuvlarni o‘z ichiga olmasligi mumkin. U zero-loss recovery kafolati emas.

Vakolatli operator o‘zgarishni bajargach mos SHA juftligi, read-only health/ready, to‘liq smoke va ta’sirlangan oqimning ruxsatli tekshiruvini qayta tasdiqlaydi. Muammoni yopish yozuvida sabab, aniq o‘zgarish, tekshiruv, qolgan xavf va keyingi mas’ul bo‘lsin. Muhim test/provider/host gate ochiq bo‘lsa “production tayyor” deyilmaydi.

## Xarajat va quvvat hisobi

| Yo‘nalish | Yig‘iladigan o‘lchov | Hozir tasdiqlanmagan qismi |
| --- | --- | --- |
| API/katalog/baza | Fixed route bo‘yicha so‘rov, 5xx/503, p95/p99 handler vaqti, CPU/RAM/disk, lock hodisasi | Hosted SLO va ogohlantirish chegarasi; lokal 1000 TEST hisob/100 faol benchmark production kafolati emas. |
| Video/storage/backup | Yuklangan va saqlangan bayt, egress, transcode xatosi/vaqti, bundle hajmi/yoshi, retention xatosi | Object storage/offsite provayderi, narx/budjet va kalit egasi. |
| SMS/MyID/xarita/push | Provayder so‘rovi, xato/kvota, yuborilgan va yetkazilgan natijani alohida hisoblash | Kelishuvlar, production credential va to‘lov hisobi. Hozir yo‘q integratsiya uchun sarf/yetkazish uydirilmaydi. |
| Support/moderatsiya/moliya | Ochiq/muddati o‘tgan ish, tayinlash va javob/qaror vaqti | Navbatchi jadvali, kundalik tekshiruv egasi, umumiy SLA. |

Alert yoki byudjet oshganda kimga va qaysi kanalga xabar borishi kelishilib, test xabari amalda olingandan keyingina monitoring yopiladi. Ushbu hujjat hech kimga xabar yubormaydi va yangi avtomatsiya yaratmaydi.
