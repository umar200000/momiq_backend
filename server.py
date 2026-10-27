"""Momiq local API. Python 3.12+, SQLite; no third-party runtime dependencies."""
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
from urllib.parse import urlparse
from config import Settings

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

def sitter_profiles():
    with db() as con:
        return [dict(json.loads(r['profile']), id=r['id']) for r in con.execute('SELECT id,profile FROM sitters WHERE active=1 ORDER BY id')]

def sitter_names():
    return {s['id']: s.get('name', '') for s in sitter_profiles()}

def photo(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 4_200_000:
        raise ValueError("Rasm 3 MB dan kichik bo‘lishi kerak")
    raw = base64.b64decode(value, validate=True)
    if not (raw.startswith(b"\x89PNG\r\n\x1a\n") or raw.startswith(b"\xff\xd8\xff") or (raw[:4] == b"RIFF" and raw[8:12] == b"WEBP")):
        raise ValueError("PNG, JPEG yoki WebP rasm yuboring")
    return value

def string(value, limit=100):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError("Matn uzunligi noto‘g‘ri")
    return value.strip()

def default_account():
    return {"profile": {"first": "", "last": "", "photo": None}, "favorites": [],
            "addresses": [], "notifications": {"orders": True, "chat": True, "video": True}, "language": "uz", "pets": [], "support": [], "sitterProfile": None}

def validate_account(data):
    result = default_account()
    p = data.get("profile", {})
    result["profile"] = {"first": string(p.get("first", "")), "last": string(p.get("last", "")), "photo": photo(p.get("photo"))}
    if not result["profile"]["first"] or not result["profile"]["last"]:
        raise ValueError("Ism va familiya majburiy")
    fav = data.get("favorites", [])
    if not isinstance(fav, list) or any(x not in sitter_names() for x in fav):
        raise ValueError("Enaga noto‘g‘ri")
    result["favorites"] = list(dict.fromkeys(fav))
    addresses = data.get("addresses", [])
    if not isinstance(addresses, list) or len(addresses) > 30:
        raise ValueError("Manzillar soni noto‘g‘ri")
    for item in addresses:
        if not isinstance(item, dict):
            raise ValueError("Manzil noto‘g‘ri")
        for key in ["id", "label", "address", "apartment"]:
            string(item.get(key, ""), 500)
        lat, lon = item.get("lat"), item.get("lon")
        if not isinstance(lat, (int,float)) or not isinstance(lon, (int,float)) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError("Manzil koordinatalari noto‘g‘ri")
    result["addresses"] = addresses
    result["notifications"] = {k: data.get("notifications", {}).get(k, True) for k in ["orders", "chat", "video"]}
    if any(type(v) is not bool for v in result["notifications"].values()):
        raise ValueError("Sozlama noto‘g‘ri")
    result["language"] = data.get("language", "uz")
    if result["language"] not in ["uz", "ru", "en"]:
        raise ValueError("Til noto‘g‘ri")
    pets = data.get('pets', [])
    if not isinstance(pets, list) or len(pets) > 30: raise ValueError('Hayvonlar soni noto‘g‘ri')
    for pet in pets:
        if not isinstance(pet, dict) or pet.get('type') not in ['It','Mushuk','Boshqa']: raise ValueError('Hayvon turi noto‘g‘ri')
        if not photo(pet.get('photo')): raise ValueError('Hayvon rasmi majburiy')
        for key in ['id','name','age','sex','breed','notes','otherType']:
            string(pet.get(key,''),2000)
        if pet['type'] == 'Boshqa' and not pet.get('otherType','').strip(): raise ValueError('Hayvon turini yozing')
    result['pets'] = pets
    support = data.get('support', [])
    if not isinstance(support,list) or len(support)>100: raise ValueError('Murojaatlar soni noto‘g‘ri')
    for item in support:
        string(item['id'],100)
        string(item['text'],4000)
    sitter = data.get('sitterProfile')
    if sitter is not None:
        if not isinstance(sitter, dict): raise ValueError('Enaga profili noto‘g‘ri')
        years = sitter.get('years')
        if years is not None and (type(years) is not int or not 0 <= years <= 80): raise ValueError('Tajriba noto‘g‘ri')
        homes = sitter.get('homePhotos', [])
        if not isinstance(homes, list) or len(homes) > 9: raise ValueError('Rasmlar soni noto‘g‘ri')
        housing = sitter.get('housing', 'apartment')
        if housing not in ['apartment','house']: raise ValueError('Uy turi noto‘g‘ri')
        result['sitterProfile'] = {'years': years, 'about': string(sitter.get('about',''),4000),
                                  'homePhotos': [photo(v) for v in homes], 'housing': housing}
    result['support'] = support
    return result

def validate_listings(data):
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
        # Never log request bodies, credentials or tokens.
        print(self.address_string(), fmt % args)
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
        size = int(self.headers.get("Content-Length", "0"))
        if size <= 0 or size > 32_000_000:
            raise ApiError(413, "So‘rov hajmi noto‘g‘ri")
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            raise ApiError(415, "JSON yuboring")
        obj = json.loads(self.rfile.read(size))
        if not isinstance(obj, dict):
            raise ValueError("JSON obyekt yuboring")
        return obj
    def auth(self, con, role="client"):
        token = self.headers.get("Authorization", "").removeprefix("Bearer ")
        if role == "admin":
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            token = cookie["momiq_admin"].value if "momiq_admin" in cookie else ""
        digest = hashlib.sha256(token.encode()).hexdigest()
        session = con.execute("SELECT * FROM sessions WHERE hash=? AND role=? AND expires>?", (digest,role,time.time())).fetchone()
        if not session:
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
    def audit(self, con, action, target):
        con.execute("INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)", ("admin",action,target,now()))
    def messages(self, con, user):
        return [{"id": r["id"], "sitter": r["sitter"], "mine": bool(r["mine"]),
                 "text": "Xabar o‘chirildi" if r["deleted"] else r["text"],
                 "image": None if r["deleted"] else r["image"], "time": r["time"]}
                for r in con.execute("SELECT * FROM messages WHERE user_id=? ORDER BY time,id", (user,))]
    def handle_request(self):
        path = urlparse(self.path).path
        origin = self.headers.get("Origin")
        if origin and (urlparse(origin).netloc != self.headers.get("Host") or (PRODUCTION and urlparse(origin).scheme != "https")):
            raise ApiError(403, "Origin ruxsat etilmagan")
        if self.command == "GET" and not path.startswith("/api/"):
            name = {"/": "index.html", "/admin": "index.html", "/admin/": "index.html", "/admin/app.js": "app.js", "/admin/style.css": "style.css"}.get(path)
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
            if path == "/api/sitters" and self.command == "GET":
                self.reply(200, {"sitters": sitter_profiles()})
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
                self.reply(200, {"token": token, "userId": user["id"], "account": json.loads(user["account"])})
                return
            if path == "/api/admin/login" and self.command == "POST":
                data = self.body()
                self.throttle(con, "admin:" + self.client_ip())
                row = con.execute("SELECT * FROM admins WHERE username=?", (string(data.get("username","")),)).fetchone()
                if not row or not hmac.compare_digest(row["hash"],password_hash(string(data.get("password",""),200),row["salt"])):
                    raise ApiError(401,"Login yoki parol noto‘g‘ri")
                token = self.session(con,row["username"],"admin")
                con.commit()
                self.reply(200, {"ok":True}, "momiq_admin="+token+"; HttpOnly; SameSite=Strict; Path=/api/admin; Max-Age=604800")
                return
            admin = path.startswith("/api/admin/")
            user = self.auth(con,"admin" if admin else "client")
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
            if path == "/api/me" and self.command in ["GET","PUT"]:
                if self.command == "PUT":
                    account = validate_account(self.body())
                    con.execute("UPDATE users SET account=? WHERE id=?", (json.dumps(account),user))
                    if account.get('sitterProfile') is not None:
                        con.execute("INSERT OR IGNORE INTO user_roles VALUES(?,'sitter')",(user,))
                row = con.execute("SELECT * FROM users WHERE id=?", (user,)).fetchone()
                con.commit()
                self.reply(200,{"userId":user,"phone":row["phone"],"account":json.loads(row["account"])})
                return
            if path == '/api/me/listings' and self.command in ['GET','PUT']:
                account = json.loads(con.execute('SELECT account FROM users WHERE id=?',(user,)).fetchone()[0])
                if self.command == 'PUT':
                    if not account.get('sitterProfile'): raise ApiError(403,'Avval enaga profilini to‘ldiring')
                    data = validate_listings(self.body())
                    con.execute('INSERT INTO listings VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET data=excluded.data,updated=excluded.updated',(user,json.dumps(data),now()))
                    con.commit()
                row = con.execute('SELECT data FROM listings WHERE user_id=?',(user,)).fetchone()
                self.reply(200,json.loads(row[0]) if row else {'housing':(account.get('sitterProfile') or {}).get('housing','apartment'),'listings':[]})
                return
            if path == '/api/admin/listings' and self.command == 'GET':
                items = []
                for r in con.execute('SELECT l.*,u.phone,u.account,u.blocked FROM listings l JOIN users u ON u.id=l.user_id ORDER BY l.updated DESC'):
                    data = json.loads(r['data'])
                    for item in data['listings']:
                        items.append(dict(item,id=r['user_id']+':'+item['type'],userId=r['user_id'],phone=r['phone'],profile=json.loads(r['account'])['profile'],blocked=bool(r['blocked']),housing=data['housing'],updated=r['updated']))
                self.reply(200,{'listings':items})
                return
            if path == "/api/messages" and self.command == "GET":
                self.reply(200,{"messages":self.messages(con,user)})
                return
            if path == "/api/messages" and self.command == "POST":
                self.save_message(con,user,True,self.body())
                return
            if path == "/api/admin/users" and self.command == "GET":
                users = [{"id":r["id"],"phone":r["phone"],"blocked":bool(r["blocked"]),"created":r["created"],"roles":roles_for(con,r["id"]),"account":json.loads(r["account"])} for r in con.execute("SELECT * FROM users ORDER BY created DESC")]
                self.reply(200,{"users":users,"sitters":sitter_names()})
                return
            match = re.fullmatch(r"/api/admin/users/([a-f0-9]+)(/messages)?", path)
            if match:
                uid, chat = match.groups()
                row = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
                if not row:
                    raise ApiError(404,"Mijoz topilmadi")
                if chat and self.command == "GET":
                    self.reply(200,{"messages":self.messages(con,uid)})
                    return
                if chat and self.command == "POST":
                    if row['blocked']:
                        raise ApiError(409,"Hisob bloklangan")
                    self.save_message(con,uid,False,self.body())
                    return
                if not chat and self.command == "PUT":
                    data = self.body()
                    if type(data.get('blocked',False)) is not bool:
                        raise ValueError('Holat noto‘g‘ri')
                    account = validate_account(data['account']) if 'account' in data else json.loads(row['account'])
                    con.execute("UPDATE users SET account=?,blocked=? WHERE id=?", (json.dumps(account),int(data.get('blocked',False)),uid))
                    self.audit(con,'update-user',uid)
                    con.commit()
                    self.reply(200,{"ok":True})
                    return
            match = re.fullmatch(r"/api/admin/messages/([a-f0-9]+)",path)
            if match and self.command == 'DELETE':
                changed = con.execute("UPDATE messages SET deleted=1,text='',image=NULL WHERE id=?", (match[1],)).rowcount
                if not changed: raise ApiError(404,'Xabar topilmadi')
                self.audit(con,'delete-message',match[1])
                con.commit()
                self.reply(200,{"ok":True})
                return
            raise ApiError(404,"Topilmadi")
    def save_message(self,con,user,mine,data):
        sitter = data.get('sitter')
        if sitter not in sitter_names(): raise ValueError('Enaga topilmadi')
        text = string(data.get('text',''),4000)
        image = photo(data.get('image'))
        if not text and not image: raise ValueError('Xabar yoki rasm kiriting')
        request_id = string(data.get('requestId',secrets.token_hex(16)),100)
        existing = con.execute('SELECT * FROM messages WHERE user_id=? AND request_id=?',(user,request_id)).fetchone()
        if existing:
            if bool(existing['mine']) != mine or existing['sitter'] != sitter:
                raise ApiError(409,'So‘rov identifikatori takrorlangan')
        else:
            con.execute('INSERT INTO messages(id,user_id,sitter,mine,text,image,time,request_id) VALUES(?,?,?,?,?,?,?,?)',
                        (secrets.token_hex(16),user,sitter,int(mine),text,image,now(),request_id))
            if not mine: self.audit(con,'reply',user)
        con.commit()
        self.reply(200,{'messages':self.messages(con,user)})
    def dispatch(self):
        try: self.handle_request()
        except ApiError as e: self.reply(e.status,{'error':e.message})
        except (ValueError,KeyError,TypeError): self.reply(400,{'error':'Ma’lumotlarni tekshiring'})
        except (BrokenPipeError,ConnectionResetError): pass
        except Exception as e:
            print(type(e).__name__)
            self.reply(500,{'error':'Server xatosi'})
    do_GET = do_POST = do_PUT = do_DELETE = dispatch

if __name__ == '__main__':
    setup()
    print(f'Momiq API: http://{HOST}:{PORT}/api/health')
    print(f'Admin: http://{HOST}:{PORT}/admin/ | credentials: {DATA / "admin-login.txt"}')
    ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
