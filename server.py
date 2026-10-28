"""Momiq API. Python 3.12, SQLite and bounded Pillow upload decoding."""
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from config import Settings
from migrations import migrate
import wallet
import request_json
import catalog
import sitter_availability
import catalog_search
import admin_accounts
import pet_safety
import sitter_dashboard
import notifications
import conversations
import chat_moderation
import booking_engine
import admin_bookings
import booking_reviews
import support_tickets
import booking_disputes
import booking_http
import booking_videos
from video_media import VideoUnavailable
from media_validation import validate_photo, MediaBusy

ROOT = Path(__file__).resolve().parent
SETTINGS = Settings.load(os.environ, ROOT)
ENVIRONMENT = SETTINGS.environment
DATA, ADMIN = SETTINGS.data, SETTINGS.admin
# Hosted staging uses the same cookie/origin transport protections as production.
PRODUCTION = ENVIRONMENT in {'staging', 'production'}
DEV_LOGIN = SETTINGS.test_login
HOST, PORT = SETTINGS.host, SETTINGS.port

def instance_id():
    return hashlib.sha256(str(DATA.resolve()).encode()).hexdigest()[:16]

def now():
    return datetime.now(timezone.utc).isoformat()

class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()

def db():
    con = sqlite3.connect(DATA / "momiq.sqlite3", timeout=20, factory=ClosingConnection)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con

def password_hash(value, salt):
    return hashlib.pbkdf2_hmac("sha256", value.encode(), bytes.fromhex(salt), 200000).hex()

def setup():
    DATA.mkdir(parents=True, exist_ok=True)
    with db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS runtime_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        row = con.execute("SELECT value FROM runtime_metadata WHERE key='environment'").fetchone()
        if row and row[0] != ENVIRONMENT:
            raise ValueError('This database belongs to a different environment; use a separate data directory')
        con.execute("INSERT OR IGNORE INTO runtime_metadata VALUES('environment',?)", (ENVIRONMENT,))
        con.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS sitters(id TEXT PRIMARY KEY, profile TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, phone TEXT UNIQUE NOT NULL,
          account TEXT NOT NULL, blocked INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS user_roles(user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, role TEXT NOT NULL, PRIMARY KEY(user_id,role));
        CREATE TABLE IF NOT EXISTS listings(user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, data TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS admins(username TEXT PRIMARY KEY, salt TEXT NOT NULL, hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, role TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
          sitter TEXT NOT NULL, mine INTEGER NOT NULL, text TEXT NOT NULL, image TEXT, time TEXT NOT NULL,
          request_id TEXT, deleted INTEGER NOT NULL DEFAULT 0, UNIQUE(user_id,request_id));
        CREATE INDEX IF NOT EXISTS messages_thread ON messages(user_id,sitter,time);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, actor TEXT, action TEXT, target TEXT, time TEXT);
        CREATE TABLE IF NOT EXISTS attempts(key TEXT PRIMARY KEY, count INTEGER, reset REAL);
        """)
        for row in con.execute("SELECT id,account FROM users WHERE id NOT IN (SELECT user_id FROM user_roles)").fetchall():
            account = json.loads(row['account'])
            role = 'sitter' if account.get('sitterProfile') is not None else 'customer'
            con.execute('INSERT INTO user_roles VALUES(?,?)', (row['id'],role))
        if not con.execute("SELECT 1 FROM admins").fetchone():
            password = os.environ.get("MOMIQ_ADMIN_PASSWORD") or secrets.token_urlsafe(16)
            salt = secrets.token_hex(16)
            con.execute("INSERT INTO admins VALUES(?,?,?)", ("admin", salt, password_hash(password, salt)))
            (DATA / "admin-login.txt").write_text("Username: admin\nPassword: " + password + "\n", encoding="utf-8")
            if os.name != "nt":
                (DATA / "admin-login.txt").chmod(0o600)
        con.commit()
        migrate(con)

def account_snapshot(con, row):
    snapshot = con.execute('SELECT u.account, COALESCE(r.revision,0) revision FROM users u LEFT JOIN account_revisions r ON r.user_id=u.id WHERE u.id=?', (row['id'],)).fetchone()
    account = json.loads(snapshot['account'])
    account['_revision'] = snapshot['revision']
    return account

def claim_account_revision(con, uid, revision):
    if revision is None:
        raise ApiError(428, 'Ilovani yangilang va profilni qayta yuklang')
    if type(revision) is not int or revision < 0:
        raise ValueError('Profil versiyasi noto‘g‘ri')
    con.execute('INSERT OR IGNORE INTO account_revisions(user_id) VALUES(?)', (uid,))
    if not con.execute('UPDATE account_revisions SET revision=revision+1 WHERE user_id=? AND revision=?', (uid,revision)).rowcount:
        raise ApiError(409, 'Profil boshqa qurilmada o‘zgargan. Qayta yuklab, o‘zgarishni takrorlang.')

def sitter_profiles():
    with db() as con:
        con.execute('BEGIN')
        return catalog.profiles(con, ENVIRONMENT)

def sitter_names():
    with db() as con:
        return catalog.known_names(con)

def photo(value):
    return validate_photo(value)

def string(value, limit=100):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError("Matn uzunligi noto‘g‘ri")
    return value.strip()

def default_account():
    return {"profile": {"first": "", "last": "", "photo": None}, "favorites": [],
            "addresses": [], "notifications": {"orders": True, "chat": True, "video": True}, "language": "uz", "pets": [], "support": [], "sitterProfile": None}

def validate_account(data):
    if not isinstance(data,dict): raise ValueError('Hisob noto‘g‘ri')
    result = default_account()
    p = data.get("profile", {})
    if not isinstance(p,dict): raise ValueError('Profil noto‘g‘ri')
    result["profile"] = {"first": string(p.get("first", "")), "last": string(p.get("last", "")), "photo": photo(p.get("photo"))}
    if not result["profile"]["first"] or not result["profile"]["last"]:
        raise ValueError("Ism va familiya majburiy")
    fav = data.get("favorites", [])
    if not isinstance(fav, list) or any(not isinstance(x, str) for x in fav):
        raise ValueError("Enaga noto‘g‘ri")
    known = sitter_names()
    if any(x not in known for x in fav):
        raise ValueError("Enaga noto‘g‘ri")
    result["favorites"] = list(dict.fromkeys(fav))
    addresses = data.get("addresses", [])
    if not isinstance(addresses, list) or len(addresses) > 30:
        raise ValueError("Manzillar soni noto‘g‘ri")
    normalized_addresses, address_ids = [], set()
    for item in addresses:
        if not isinstance(item, dict):
            raise ValueError("Manzil noto‘g‘ri")
        normalized = {key:string('' if item.get(key) is None else item[key],500) for key in ["id", "label", "address", "apartment"]}
        if not normalized['id'] or normalized['id'] in address_ids or not normalized['address']: raise ValueError('Manzil ID yoki matni noto‘g‘ri')
        address_ids.add(normalized['id'])
        lat, lon = item.get("lat"), item.get("lon")
        if type(lat) not in (int,float) or type(lon) not in (int,float) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError("Manzil koordinatalari noto‘g‘ri")
        normalized_addresses.append(dict(normalized,lat=lat,lon=lon))
    result["addresses"] = normalized_addresses
    notifications = data.get('notifications', {})
    if not isinstance(notifications,dict): raise ValueError('Sozlamalar noto‘g‘ri')
    result["notifications"] = {k: notifications.get(k, True) for k in ["orders", "chat", "video"]}
    if any(type(v) is not bool for v in result["notifications"].values()):
        raise ValueError("Sozlama noto‘g‘ri")
    result["language"] = data.get("language", "uz")
    if result["language"] not in ["uz", "ru", "en"]:
        raise ValueError("Til noto‘g‘ri")
    pets = data.get('pets', [])
    if not isinstance(pets, list) or len(pets) > 30: raise ValueError('Hayvonlar soni noto‘g‘ri')
    normalized_pets = []
    pet_ids = set()
    for pet in pets:
        if not isinstance(pet, dict) or pet.get('type') not in ['It','Mushuk','Boshqa']: raise ValueError('Hayvon turi noto‘g‘ri')
        if not photo(pet.get('photo')): raise ValueError('Hayvon rasmi majburiy')
        item = {key:string('' if pet.get(key) is None else pet[key],100 if key=='id' else 2000) for key in ['id','name','age','sex','breed','notes','otherType']}
        item.update(pet_safety.validate(pet))
        if not item['id'] or item['id'] in pet_ids: raise ValueError('Hayvon ID takrorlangan yoki bo‘sh')
        pet_ids.add(item['id'])
        if item['age'] and (not item['age'].isascii() or not item['age'].isdigit() or not 0<=int(item['age'])<=100): raise ValueError('Hayvon yoshi noto‘g‘ri')
        if item['sex'] not in ['', 'Erkak', 'Urg‘ochi']: raise ValueError('Jins noto‘g‘ri')
        if pet['type'] == 'Boshqa' and not item['otherType']: raise ValueError('Hayvon turini yozing')
        archived = pet.get('archived', False)
        if type(archived) is not bool: raise ValueError('Hayvon arxiv holati noto‘g‘ri')
        normalized_pets.append(dict(item,type=pet['type'],photo=pet['photo'],archived=archived))
    result['pets'] = normalized_pets
    support = data.get('support', [])
    if not isinstance(support,list) or len(support)>100: raise ValueError('Murojaatlar soni noto‘g‘ri')
    normalized_support, support_ids = [], set()
    for item in support:
        if not isinstance(item,dict): raise ValueError('Murojaat noto‘g‘ri')
        identity, body = string(item.get('id'),100), string(item.get('text'),4000)
        if not identity or not body or identity in support_ids: raise ValueError('Murojaat ID yoki matni noto‘g‘ri')
        support_ids.add(identity)
        normalized_support.append({'id':identity,'text':body})
    sitter = data.get('sitterProfile')
    if sitter is not None:
        if not isinstance(sitter, dict): raise ValueError('Enaga profili noto‘g‘ri')
        years = sitter.get('years')
        if years is not None and (type(years) is not int or not 0 <= years <= 80): raise ValueError('Tajriba noto‘g‘ri')
        homes = sitter.get('homePhotos', [])
        if not isinstance(homes, list) or len(homes) > 9 or any(v is None for v in homes): raise ValueError('Rasmlar soni noto‘g‘ri')
        housing = sitter.get('housing', 'apartment')
        if housing not in ['apartment','house']: raise ValueError('Uy turi noto‘g‘ri')
        result['sitterProfile'] = {'years': years, 'about': string(sitter.get('about',''),4000),
                                  'homePhotos': [photo(v) for v in homes], 'housing': housing}
        schedule = sitter.get('schedule')
        if 'closedDates' in sitter:
            result['sitterProfile']['closedDates'] = sitter_availability.closed_dates(sitter['closedDates'])
        if schedule is not None:
            if not isinstance(schedule,dict): raise ValueError('Jadval noto‘g‘ri')
            days, start, end = schedule.get('days'), schedule.get('start'), schedule.get('end')
            if not isinstance(days,list) or len(days)!=7 or any(type(v) is not bool for v in days): raise ValueError('Hafta kunlari noto‘g‘ri')
            if type(start) is not int or type(end) is not int or not 0<=start<end<1440: raise ValueError('Ish vaqti noto‘g‘ri')
            result['sitterProfile']['schedule'] = {'days':days,'start':start,'end':end,'timezone':'Asia/Tashkent'}
    result['support'] = normalized_support
    return result

def validate_listings(data):
    if not isinstance(data,dict): raise ValueError('E’lonlar noto‘g‘ri')
    housing = data.get('housing')
    items = data.get('listings')
    if housing not in ['apartment','house'] or not isinstance(items,list) or len(items)>3:
        raise ValueError('E’lonlar noto‘g‘ri')
    result, seen = [], set()
    for item in items:
        if not isinstance(item,dict): raise ValueError('E’lon noto‘g‘ri')
        kind = item.get('type')
        if kind not in ['boarding','homeVisit','personal'] or kind in seen: raise ValueError('Xizmat turi noto‘g‘ri')
        seen.add(kind)
        pets = item.get('pets')
        if not isinstance(pets,list) or not pets or len(pets)>2 or any(p not in ['dog','cat'] for p in pets) or len(set(pets))!=len(pets): raise ValueError('Hayvon turi noto‘g‘ri')
        if kind!='homeVisit' and len(pets)!=1: raise ValueError('Bitta hayvon turini tanlang')
        price, active, capacity = item.get('price'),item.get('active'),item.get('capacity')
        if type(price) is not int or not 0<price<=999999999 or type(active) is not bool: raise ValueError('Narx yoki holat noto‘g‘ri')
        if kind=='boarding' and (type(capacity) is not int or not 1<=capacity<=(1 if housing=='apartment' else 3)): raise ValueError('Sig‘im noto‘g‘ri')
        location = item.get('location')
        if location is not None:
            if not isinstance(location,dict): raise ValueError('Manzil noto‘g‘ri')
            lat, lon = location.get('lat'),location.get('lon')
            if type(lat) not in [int,float] or type(lon) not in [int,float] or not -90<=lat<=90 or not -180<=lon<=180: raise ValueError('Koordinata noto‘g‘ri')
            address = string(location.get('address'),1000)
            if not address: raise ValueError('Manzil majburiy')
            location = {'lat':lat,'lon':lon,'address':address}
        if kind!='homeVisit' and location is None: raise ValueError('Manzil majburiy')
        result.append({'type':kind,'pets':pets,'price':price,'active':active,'capacity':capacity if kind=='boarding' else None,'location':location})
    active = [i['type'] for i in result if i['active']]
    if 'personal' in active and len(active)>1: raise ValueError('Xizmatlar bir vaqtda faol bo‘la olmaydi')
    return {'housing':housing,'listings':result}

def roles_for(con, uid):
    return [r[0] for r in con.execute('SELECT role FROM user_roles WHERE user_id=? ORDER BY role',(uid,))]

class ApiError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message

class Handler(BaseHTTPRequestHandler):
    server_version = "MomiqLocal/1"
    def log_message(self, fmt, *args):
        # BaseHTTPRequestHandler diagnostics can contain the raw request line.
        print('http diagnostic')
    def log_request(self, code='-', size='-'):
        from request_logging import access_record
        print(access_record(getattr(self,'command',''),getattr(self,'path',''),code))
    def reply(self, status, body, cookie=None):
        raw = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if cookie:
            self.send_header("Set-Cookie", cookie + ("; Secure" if PRODUCTION else ""))
        self.end_headers()
        self.wfile.write(raw)
    def body(self):
        try:
            return request_json.read(self)
        except (request_json.BodyError,ValueError):
            # Never reuse an HTTP connection with unread/ambiguous request bytes.
            self.close_connection=True
            raise
    def auth(self, con, role="client"):
        token = self.headers.get("Authorization", "").removeprefix("Bearer ")
        if role == "admin":
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            token = cookie["momiq_admin"].value if "momiq_admin" in cookie else ""
        digest = hashlib.sha256(token.encode()).hexdigest()
        session = con.execute("SELECT * FROM sessions WHERE hash=? AND role=? AND expires>?", (digest,role,time.time())).fetchone()
        if not session:
            raise ApiError(401, "Qayta kiring")
        if role == "admin" and not con.execute("SELECT 1 FROM admins WHERE username=?", (session["user_id"],)).fetchone():
            raise ApiError(401, "Qayta kiring")
        if role == "client":
            user = con.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
            if not user or user["blocked"]:
                raise ApiError(403, "Hisob bloklangan")
        return session["user_id"]
    def session(self, con, user, role):
        token = secrets.token_urlsafe(40)
        con.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
        con.execute("INSERT INTO sessions VALUES(?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), user, role, time.time()+86400*7))
        return token
    def client_ip(self):
        if PRODUCTION and self.client_address[0] in ('127.0.0.1', '::1'):
            return self.headers.get('X-Real-IP', self.client_address[0])
        return self.client_address[0]
    def throttle(self, con, key):
        row = con.execute("SELECT * FROM attempts WHERE key=?", (key,)).fetchone()
        count = row["count"] if row and row["reset"] > time.time() else 0
        reset = row["reset"] if count else time.time()+60
        if count >= 15:
            raise ApiError(429, "Biroz kutib qayta urinib ko‘ring")
        con.execute("INSERT OR REPLACE INTO attempts VALUES(?,?,?)", (key,count+1,reset))
        con.commit()
    def audit(self, con, actor, action, target):
        con.execute("INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)", (actor,action,target,now()))
    def messages(self, con, user):
        return [{"id": r["id"], "sitter": r["sitter"], "mine": bool(r["mine"]),
                 "senderRole": "customer" if r["mine"] else "support",
                 "text": "Xabar o‘chirildi" if r["deleted"] else r["text"],
                 "image": None if r["deleted"] else r["image"], "time": r["time"]}
                for r in con.execute("SELECT * FROM messages WHERE user_id=? ORDER BY time,id", (user,))]
    def handle_request(self):
        path = urlparse(self.path).path
        origin = self.headers.get("Origin")
        if origin and (urlparse(origin).netloc != self.headers.get("Host") or (PRODUCTION and urlparse(origin).scheme != "https")):
            raise ApiError(403, "Origin ruxsat etilmagan")
        if self.command == "GET" and not path.startswith("/api/"):
            name = {"/": "index.html", "/admin": "index.html", "/admin/": "index.html", "/admin/app.js": "app.js", "/admin/wallet.js": "wallet.js", "/admin/chat.js": "chat.js", "/admin/reviews.js": "reviews.js", "/admin/support.js": "support.js", "/admin/disputes.js": "disputes.js", "/admin/bookings.js": "bookings.js", "/admin/style.css": "style.css"}.get(path)
            if not name or not (ADMIN / name).is_file():
                raise ApiError(404, "Topilmadi")
            raw = (ADMIN / name).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(name)[0] + "; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(raw)
            return
        with db() as con:
            if booking_reviews.public_route(self,con,path,ENVIRONMENT):
                return
            if path == "/api/sitters" and self.command == "GET":
                params = parse_qs(urlparse(self.path).query, keep_blank_values=True)
                owner = self.auth(con) if params.get('favorites') == ['1'] else None
                self.reply(200, catalog_search.page(con, ENVIRONMENT, params, user=owner))
                return
            if path == "/api/health" and self.command == "GET":
                self.reply(200, {"ok": True, "mode": ENVIRONMENT, "instanceId": instance_id(), "sms": False, "clientLoginEnabled": DEV_LOGIN, "testLogin": DEV_LOGIN})
                return
            if path == "/api/auth/login" and self.command == "POST":
                if not DEV_LOGIN:
                    raise ApiError(503, "SMS orqali kirish hali ulanmagan. Keyinroq urinib ko‘ring.")
                data = self.body()
                self.throttle(con, "client:" + self.client_ip())
                phone = re.sub(r"\D", "", string(data.get("phone", ""), 30))
                if not re.fullmatch(r"998\d{9}", phone) or data.get("code") != "111111":
                    raise ApiError(401, "Telefon yoki kod noto‘g‘ri")
                user = con.execute("SELECT * FROM users WHERE phone=?", (phone,)).fetchone()
                if not user:
                    uid = secrets.token_hex(12)
                    con.execute("INSERT INTO users VALUES(?,?,?,0,?)", (uid,phone,json.dumps(default_account()),now()))
                    user = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
                if user["blocked"]:
                    raise ApiError(403, "Hisob bloklangan")
                role = data.get('role')
                if role is not None and role not in ['customer','sitter']: raise ValueError('Rol noto‘g‘ri')
                if role is None and not roles_for(con,user['id']):
                    role = 'sitter' if json.loads(user['account']).get('sitterProfile') else 'customer'
                if role:
                    con.execute('INSERT OR IGNORE INTO user_roles VALUES(?,?)',(user['id'],role))
                token = self.session(con,user["id"],"client")
                con.commit()
                self.reply(200, {"token": token, "userId": user["id"], "account": account_snapshot(con,user)})
                return
            if path == "/api/admin/login" and self.command == "POST":
                data = self.body()
                self.throttle(con, "admin:" + self.client_ip())
                # Serialize credential verification and issuance with revocation.
                con.execute('BEGIN IMMEDIATE')
                row = con.execute("SELECT * FROM admins WHERE username=?", (string(data.get("username","")),)).fetchone()
                if not row or not hmac.compare_digest(row["hash"],password_hash(string(data.get("password",""),200),row["salt"])):
                    raise ApiError(401,"Login yoki parol noto‘g‘ri")
                token = self.session(con,row["username"],"admin")
                con.commit()
                self.reply(200, {"ok":True}, "momiq_admin="+token+"; HttpOnly; SameSite=Strict; Path=/api/admin; Max-Age=604800")
                return
            admin = path.startswith("/api/admin/")
            user = self.auth(con,"admin" if admin else "client")
            if path == '/api/me/role':
                if self.command != 'POST':raise ApiError(405,'POST yuboring')
                data = self.body()
                if set(data)!={'role'} or data['role'] not in ('customer','sitter'):
                    raise ValueError('Rol noto‘g‘ri')
                con.execute('BEGIN IMMEDIATE')
                # Enrolment is self-service, never an approval or an admin grant.
                row=con.execute('SELECT * FROM users WHERE id=?',(user,)).fetchone()
                if not row or row['blocked']:raise ApiError(403,'Hisob bloklangan')
                changed = con.execute('INSERT OR IGNORE INTO user_roles VALUES(?,?)',(user,data['role'])).rowcount
                if changed:
                    con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',
                                (user,'role-enroll',data['role'],now()))
                result={'userId':user,'role':data['role'],'roles':roles_for(con,user),'account':account_snapshot(con,row)}
                con.commit()
                self.reply(200,result)
                return
            if admin_accounts.route(self,con,user,path,account_snapshot,roles_for):
                return
            if booking_videos.admin_route(self,con,user,path,DATA):
                return
            if admin_bookings.route(self,con,user,path):
                return
            if support_tickets.route(self,con,user,path,photo):
                return
            if booking_disputes.route(self,con,user,path,photo,ENVIRONMENT):
                return
            if booking_reviews.admin_route(self,con,user,path,datetime.fromisoformat(now())):
                return
            if wallet.route(self,con,user,path,photo,ENVIRONMENT):
                return
            if booking_http.route(self,con,user,path,ENVIRONMENT,DATA):
                return
            if chat_moderation.route(self,con,user,path):
                return
            if conversations.route(self,con,user,path,photo,ENVIRONMENT):
                return
            if notifications.route(self,con,user,path):
                return
            if path == '/api/auth/logout-all' and self.command == 'POST':
                con.execute("DELETE FROM sessions WHERE user_id=? AND role='client'", (user,))
                con.commit()
                self.reply(200, {'ok':True})
                return
            if path in ["/api/auth/logout", "/api/admin/logout"] and self.command == "POST":
                if admin:
                    cookie = SimpleCookie(self.headers.get('Cookie',''))
                    token = cookie['momiq_admin'].value
                else:
                    token = self.headers.get('Authorization','').removeprefix('Bearer ')
                con.execute('DELETE FROM sessions WHERE hash=?', (hashlib.sha256(token.encode()).hexdigest(),))
                con.commit()
                self.reply(200,{"ok":True}, "momiq_admin=; HttpOnly; SameSite=Strict; Path=/api/admin; Max-Age=0" if admin else None)
                return
            if path == '/api/me/pets/archive' and self.command == 'POST':
                data = self.body()
                if type(data.get('archived')) is not bool: raise ValueError('Arxiv holati majburiy')
                pet_id = string(data.get('petId'),100)
                con.execute('BEGIN IMMEDIATE')
                revision_row = con.execute('SELECT revision FROM account_revisions WHERE user_id=?',(user,)).fetchone()
                current_revision = revision_row[0] if revision_row else 0
                current = json.loads(con.execute('SELECT account FROM users WHERE id=?',(user,)).fetchone()[0])
                pet = next((p for p in current.get('pets',[]) if p['id']==pet_id),None)
                if (pet and type(data.get('_revision')) is int and data['_revision']==current_revision-1
                        and bool(pet.get('archived',False))==data['archived']):
                    row = con.execute('SELECT * FROM users WHERE id=?',(user,)).fetchone()
                    con.commit()
                    self.reply(200,{'account':account_snapshot(con,row)})
                    return
                claim_account_revision(con,user,data.get('_revision'))
                if not pet: raise ApiError(404,'Hayvon topilmadi')
                pet['archived'] = data['archived']
                con.execute('UPDATE users SET account=? WHERE id=?',(json.dumps(current),user))
                con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',
                            (user,'pet-archive' if data['archived'] else 'pet-restore',pet_id,now()))
                row = con.execute('SELECT * FROM users WHERE id=?',(user,)).fetchone()
                con.commit()
                self.reply(200,{'account':account_snapshot(con,row)})
                return
            if path == '/api/me/dashboard' and self.command == 'GET':
                self.reply(200,sitter_dashboard.overview(con,user,datetime.fromisoformat(now())))
                return
            if path == "/api/me" and self.command in ["GET","PUT"]:
                if self.command == "PUT":
                    data = self.body()
                    account = validate_account(data)
                    claim_account_revision(con, user, data.get('_revision'))
                    before = json.loads(con.execute('SELECT account FROM users WHERE id=?',(user,)).fetchone()[0])
                    # Old clients may omit archived pets or their new flag. A full
                    # profile save must not silently delete/restore those records.
                    old_pets = {p['id']:p for p in before.get('pets',[])}
                    incoming_pets = {p['id'].strip():p for p in data.get('pets',[])}
                    for pet in account['pets']:
                        old_pet = old_pets.get(pet['id'],{})
                        pet['archived'] = bool(old_pet.get('archived',False))
                        # Omitted new fields from an older client are not a clear.
                        for field in pet_safety.FIELDS:
                            if field not in incoming_pets[pet['id']]:
                                pet[field] = old_pet.get(field,'')
                    retained_ids = {p['id'] for p in account['pets']}
                    account['pets'].extend(p for key,p in old_pets.items() if key not in retained_ids)
                    if len(account['pets'])>30: raise ValueError('Arxiv bilan birga hayvonlar soni 30 dan oshmasin')
                    sitter_availability.preserve_omitted(before,account,data)
                    catalog.invalidate_profile(con,user,before,account)
                    con.execute("UPDATE users SET account=? WHERE id=?", (json.dumps(account),user))
                    if account.get('sitterProfile') is not None:
                        con.execute("INSERT OR IGNORE INTO user_roles VALUES(?,'sitter')",(user,))
                row = con.execute("SELECT * FROM users WHERE id=?", (user,)).fetchone()
                con.commit()
                self.reply(200,{"userId":user,"phone":row["phone"],"account":account_snapshot(con,row)})
                return
            if path == '/api/me/listings' and self.command in ['GET','PUT']:
                if self.command == 'PUT':
                    body = self.body()
                    result = catalog.save(con,user,validate_listings(body),body.get('_revision'))
                else:
                    result = catalog.document(con,user)
                self.reply(200,result)
                return
            match = re.fullmatch(r'/api/me/listings/(boarding|homeVisit|personal)/archive',path)
            if match and self.command == 'POST':
                self.reply(200,catalog.archive(con,user,match[1],self.body().get('_revision')))
                return
            match = re.fullmatch(r'/api/admin/listings/([a-f0-9]+)/(boarding|homeVisit|personal)/review',path)
            if match and self.command == 'POST':
                self.reply(200,catalog.review(con,*match.groups(),self.body(),user,ENVIRONMENT))
                return
            if path == "/api/messages" and self.command == "GET":
                self.reply(200,{"messages":self.messages(con,user)})
                return
            if path == "/api/messages" and self.command == "POST":
                self.save_message(con,user,True,self.body())
                return
            match = re.fullmatch(r"/api/admin/users/([a-f0-9]+)(/messages)?", path)
            if match:
                uid, chat = match.groups()
                if not chat and self.command == 'PUT':
                    con.execute('BEGIN IMMEDIATE')
                row = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
                if not row:
                    raise ApiError(404,"Mijoz topilmadi")
                if chat and self.command == "GET":
                    result={"messages":self.messages(con,uid)}
                    self.audit(con,user,'legacy-chat-view',uid)
                    con.commit()
                    self.reply(200,result)
                    return
                if chat and self.command == "POST":
                    if row['blocked']:
                        raise ApiError(409,"Hisob bloklangan")
                    self.save_message(con,uid,False,self.body(),operator=user)
                    return
                if not chat and self.command == "PUT":
                    data = self.body()
                    if type(data.get('blocked',False)) is not bool:
                        raise ValueError('Holat noto‘g‘ri')
                    account = validate_account(data['account']) if 'account' in data else json.loads(row['account'])
                    claim_account_revision(con, uid, data.get('_revision'))
                    sitter_availability.preserve_omitted(json.loads(row['account']),account,data.get('account',account))
                    catalog.invalidate_profile(con,uid,json.loads(row['account']),account)
                    blocked = int(data.get('blocked',row['blocked']))
                    con.execute("UPDATE users SET account=?,blocked=? WHERE id=?", (json.dumps(account),blocked,uid))
                    if blocked:
                        con.execute("DELETE FROM sessions WHERE user_id=? AND role='client'", (uid,))
                    self.audit(con,user,'update-user',uid)
                    con.commit()
                    self.reply(200,{"ok":True})
                    return
            match = re.fullmatch(r"/api/admin/messages/([a-f0-9]+)",path)
            if match and self.command == 'DELETE':
                changed = con.execute("UPDATE messages SET deleted=1,text='',image=NULL WHERE id=?", (match[1],)).rowcount
                if not changed: raise ApiError(404,'Xabar topilmadi')
                self.audit(con,user,'delete-message',match[1])
                con.commit()
                self.reply(200,{"ok":True})
                return
            raise ApiError(404,"Topilmadi")
    def save_message(self,con,user,mine,data,operator=None):
        if not mine and operator is None:raise ApiError(403,'Operator sessiyasi kerak')
        sitter = data.get('sitter')
        if sitter not in sitter_names(): raise ValueError('Enaga topilmadi')
        text = string(data.get('text',''),4000)
        image = photo(data.get('image'))
        if not text and not image: raise ValueError('Xabar yoki rasm kiriting')
        request_id = string(data.get('requestId',secrets.token_hex(16)),100)
        con.execute('BEGIN IMMEDIATE')
        existing = con.execute('SELECT * FROM messages WHERE user_id=? AND request_id=?',(user,request_id)).fetchone()
        if existing:
            if (bool(existing['mine']) != mine or existing['sitter'] != sitter
                    or existing['text'] != text or existing['image'] != image):
                raise ApiError(409,'So‘rov identifikatori takrorlangan')
        else:
            if mine and not con.execute('SELECT 1 FROM messages WHERE user_id=? AND sitter=? LIMIT 1',(user,sitter)).fetchone():
                if sitter not in {s['id'] for s in catalog.profiles(con,ENVIRONMENT)}:
                    raise ApiError(409,'Bu enaga hozir yangi mijoz qabul qilmayapti. Katalogni yangilang.')
            con.execute('INSERT INTO messages(id,user_id,sitter,mine,text,image,time,request_id) VALUES(?,?,?,?,?,?,?,?)',
                        (secrets.token_hex(16),user,sitter,int(mine),text,image,now(),request_id))
            if not mine: self.audit(con,operator,'reply',user)
        con.commit()
        self.reply(200,{'messages':self.messages(con,user)})
    def dispatch(self):
        try: self.handle_request()
        except (ApiError,request_json.BodyError,wallet.WalletError,catalog.CatalogError,notifications.NotificationError,conversations.ChatError,booking_engine.BookingError) as e: self.reply(e.status,{'error':e.message})
        except (MediaBusy, VideoUnavailable) as e: self.reply(503,{'error':str(e)})
        except (ValueError,KeyError,TypeError): self.reply(400,{'error':'Ma’lumotlarni tekshiring'})
        except (BrokenPipeError,ConnectionResetError): pass
        except Exception as e:
            print(type(e).__name__)
            self.reply(500,{'error':'Server xatosi'})
    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = dispatch

if __name__ == '__main__':
    setup()
    print(f'Momiq API: http://{HOST}:{PORT}/api/health')
    print(f'Admin: http://{HOST}:{PORT}/admin/ | credentials: {DATA / "admin-login.txt"}')
    http = ThreadingHTTPServer((HOST,PORT),Handler)
    worker = None
    if ENVIRONMENT in ('local', 'test'):
        from booking_worker import ExpiryWorker
        worker = ExpiryWorker(db, ENVIRONMENT, media_root=DATA)
        worker.start()
    try:
        http.serve_forever()
    finally:
        if worker:
            worker.stop()
        http.server_close()
