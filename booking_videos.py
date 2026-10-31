"""Private video reports. Files become visible only after a committed DB record.

Storage is inside the instance data directory, never the public admin tree.
Original uploads are temporary; only normalized playback/poster files persist.
"""
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from pathlib import Path
import os
import json
import re
import secrets
import shutil
import stat
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlparse

import booking_care as care
import booking_engine as engine
import conversations
import notifications
import video_media as media
import video_policy as policy
import video_retention
import video_followup

_uploads = threading.BoundedSemaphore(2)


def metadata(row):
    return {'id': row['id'], 'petId': row['pet_id'], 'day': row['day'], 'slot': row['slot'],
            'durationMs': row['duration_ms'], 'bytes': row['bytes'], 'width': row['width'],
            'height': row['height'], 'created': row['created']}


def acknowledgement(row,identity):
    return {**metadata(row),'bookingId':identity,'requestId':row['request_id']}


def options(data):
    if not isinstance(data, dict) or set(data) != {'petId', 'day', 'slot', 'requestId'}:
        raise ValueError('Invalid video fields')
    if not isinstance(data['petId'], str) or not 1 <= len(data['petId']) <= 120:
        raise ValueError('Invalid pet')
    care.day_value(data['day'])
    if not isinstance(data['slot'],str) or data['slot'] not in policy.SLOTS:
        raise ValueError('Invalid video slot')
    engine.retry_key(data['requestId'], data)
    return data


def prior(con, user, fingerprint, request):
    row = con.execute('SELECT * FROM booking_videos WHERE actor=? AND request_id=?', (user, request)).fetchone()
    if row and row['fingerprint'] != fingerprint:
        raise engine.BookingError(409, 'Bu so‘rov boshqa video uchun ishlatilgan')
    return row


def writable(con, identity, user, data, now):
    booking = care.access(con, identity, user)
    if booking['myRole'] != 'sitter' or booking['status'] != 'active':
        raise engine.BookingError(403, 'Video faqat faol buyurtmaning enagasi tomonidan yuboriladi')
    if not any(p['id'] == data['petId'] for p in booking['snapshot']['pets']):
        raise engine.BookingError(404, 'Hayvon bu buyurtmaga tegishli emas')
    policy.require_window(data['day'], data['slot'], now)
    if con.execute('SELECT 1 FROM booking_videos WHERE booking_id=? AND pet_id=? AND day=? AND slot=?',
                   (identity, data['petId'], data['day'], data['slot'])).fetchone():
        raise engine.BookingError(409, 'Bu vaqt uchun video allaqachon saqlangan. Sahifani yangilang')
    return booking


def readable(con, identity, user, admin=False):
    if not admin:return care.access(con,identity,user)
    row=con.execute('SELECT b.status,q.snapshot FROM bookings b JOIN booking_quotes q ON q.id=b.quote_id WHERE b.id=?',(identity,)).fetchone()
    if not row:raise engine.BookingError(404,'Buyurtma topilmadi')
    return {'status':row['status'],'snapshot':json.loads(row['snapshot']),'myRole':'admin'}


def overview(con, identity, user, day, now, *, admin=False):
    con.execute('BEGIN')
    booking = readable(con, identity, user, admin)
    rules = policy.policy(now)
    day = rules['today'] if day is None else care.day_value(day)
    if day > rules['today']:
        raise ValueError('Future video day')
    rows = con.execute('SELECT * FROM booking_videos WHERE booking_id=? AND day=? ORDER BY pet_id,slot', (identity, day)).fetchall()
    return {'bookingId': identity, 'day': day, 'policy': rules, 'status': booking['status'],
            'canUpload': booking['myRole'] == 'sitter' and booking['status'] == 'active' and day == rules['today'] and media.available(),
            'serviceAvailable': media.available(),
            'pets': [{'id': p['id'], 'name': p.get('name') or p['type']} for p in booking['snapshot']['pets']],
            'retentionDays': 30,
            'followups': video_followup.overview(con,identity,user,day,now,booking['myRole']),
            'items': [dict(metadata(row),**video_retention.status(con,row,now)) for row in rows]}


def store(con, root, identity, user, data, source, clock):
    """Owns its transaction: decode outside DB lock, recheck before publication."""
    options(data)
    fingerprint = engine.retry_key(data['requestId'], {'booking': identity, **data, 'sha256': media.sha256(source)})
    care.access(con, identity, user)
    old = prior(con, user, fingerprint, data['requestId'])
    if old:
        return acknowledgement(old,identity)
    writable(con, identity, user, data, clock())
    root = Path(root)/'care-videos'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix='.processing-', dir=root) as temporary:
        prepared = media.prepare(source, temporary)
        destination = None
        try:
            engine.begin(con)
            care.access(con, identity, user)
            old = prior(con, user, fingerprint, data['requestId'])
            if old:
                con.rollback()
                return acknowledgement(old,identity)
            now = clock()
            writable(con, identity, user, data, now)
            video_id = secrets.token_hex(16)
            candidate = root/video_id
            candidate.mkdir(mode=0o700)
            destination = candidate
            # Flush complete derivatives before committing their references.
            for key, filename in [('videoFile', 'playback.mp4'), ('posterFile', 'poster.jpg')]:
                target = destination/filename
                with Path(prepared[key]).open('rb') as incoming, target.open('wb') as stream:
                    shutil.copyfileobj(incoming, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
            if os.name != 'nt':
                for folder in (destination,root):
                    descriptor = os.open(folder,os.O_RDONLY | os.O_DIRECTORY)
                    try: os.fsync(descriptor)
                    finally: os.close(descriptor)
            con.execute('INSERT INTO booking_videos VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (video_id,identity,data['petId'],data['day'],data['slot'],user,data['requestId'],fingerprint,
                 prepared['durationMs'],prepared['bytes'],prepared['width'],prepared['height'],
                 prepared['videoHash'],prepared['posterHash'],engine.stamp(now)))
            con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',
                        (user,'care-video',engine.encode({'bookingId':identity,'videoId':video_id}),engine.stamp(now)))
            customer = engine.owned(con, identity, user)['customer_id']
            notifications.publish(con, customer, f'care-video:{video_id}', 'care', identity, 'video', '')
            result = acknowledgement(con.execute('SELECT * FROM booking_videos WHERE id=?', (video_id,)).fetchone(),identity)
            con.commit()
            return result
        except BaseException:
            con.rollback()
            if destination is not None:
                # Only this call's randomly allocated private directory.
                shutil.rmtree(destination)
            raise


def byte_range(value, size):
    if value is None:
        return 0, size-1, 200
    match = re.fullmatch(r'bytes=(\d*)-(\d*)', value)
    if not match or not (match[1] or match[2]):
        raise engine.BookingError(416, 'Noto‘g‘ri video oralig‘i')
    if not match[1]:
        suffix = int(match[2])
        if suffix <= 0:
            raise engine.BookingError(416, 'Noto‘g‘ri video oralig‘i')
        return max(0,size-suffix),size-1,206
    start = int(match[1]); end = min(int(match[2]),size-1) if match[2] else size-1
    if start > end or start >= size:
        raise engine.BookingError(416, 'Noto‘g‘ri video oralig‘i')
    return start,end,206


@contextmanager
def open_derivative(root, video, kind):
    """Open one regular, privately stored derivative under the configured data root."""
    names = {'playback': 'playback.mp4', 'poster': 'poster.jpg'}
    if not re.fullmatch('[a-f0-9]{32}', video) or kind not in names:
        raise media.VideoUnavailable('Video fayli hozir mavjud emas')
    with ExitStack() as stack:
        try:
            root = Path(root).resolve(strict=True)
            parts = ('care-videos', video, names[kind])
            if os.name == 'posix':
                directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                directory = os.open(root, directory_flags)
                stack.callback(os.close, directory)
                for component in parts[:-1]:
                    directory = os.open(component, directory_flags, dir_fd=directory)
                    stack.callback(os.close, directory)
                fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory)
            else:
                path = root
                for component in parts:
                    path = path / component
                    if path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                        raise OSError('Unexpected reparse point')
                fd = os.open(path, os.O_RDONLY | os.O_BINARY)
            stack.callback(os.close, fd)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size <= 0:
                raise OSError('Invalid private media file')
            if os.name != 'posix' and (path.resolve(strict=True) != path or
                                       not os.path.samestat(info, path.stat())):
                raise OSError('Private media path changed')
            stream = stack.enter_context(os.fdopen(fd, 'rb', closefd=False))
        except OSError as error:
            raise media.VideoUnavailable('Video fayli hozir mavjud emas') from error
        yield stream


def download(handler, con, root, identity, user, video, kind, *, admin=False):
    readable(con, identity, user, admin)
    row = con.execute('SELECT * FROM booking_videos WHERE id=? AND booking_id=?', (video,identity)).fetchone()
    if not row:
        raise engine.BookingError(404, 'Video topilmadi')
    if not video_retention.status(con,row,datetime.now(timezone.utc))['available']:
        raise engine.BookingError(410, 'Videoning saqlash muddati tugagan')
    with open_derivative(root, row['id'], kind) as stream:
        size = os.fstat(stream.fileno()).st_size
        start,end,status = byte_range(handler.headers.get('Range'),size)
        if admin:
            con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',
                (user,'admin-view-booking-video',engine.encode({'bookingId':identity,'videoId':video,'kind':kind}),engine.stamp(datetime.now(timezone.utc))))
            con.commit()
        handler.send_response(status)
        for key,value in {'Content-Type':'video/mp4' if kind=='playback' else 'image/jpeg',
                          'Content-Length':str(end-start+1),'Accept-Ranges':'bytes',
                          'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff',
                          'Content-Disposition':'inline','Vary':'Cookie' if admin else 'Authorization'}.items():
            handler.send_header(key,value)
        if status == 206:
            handler.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        handler.end_headers()
        stream.seek(start); remaining = end-start+1
        while remaining:
            chunk = stream.read(min(65536,remaining))
            if not chunk: break
            handler.wfile.write(chunk); remaining -= len(chunk)


def admin_route(handler, con, user, path, root):
    # server.Handler has already required the HttpOnly admin session for this
    # namespace. This is read-only and cannot turn a report into a care finding.
    match=re.fullmatch(r'/api/admin/bookings/([a-f0-9]{32})/videos(?:/([a-f0-9]{32})/(playback|poster))?',path)
    if not match:return False
    if handler.command!='GET':raise engine.BookingError(405,'Faqat ko‘rish mumkin')
    query=parse_qs(urlparse(handler.path).query,keep_blank_values=True)
    if any(len(v)!=1 for v in query.values()) or set(query)-{'day'} or (match[2] and query):
        raise ValueError('Invalid admin video query')
    if match[2]:
        download(handler,con,root,match[1],user,match[2],match[3],admin=True)
    else:
        result=overview(con,match[1],user,query.get('day',[None])[0],datetime.now(timezone.utc),admin=True)
        con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',
            (user,'admin-view-booking-videos',match[1],engine.stamp(datetime.now(timezone.utc))))
        con.commit();handler.reply(200,result)
    return True


def route(handler, con, user, path, root, clock=lambda: datetime.now(timezone.utc)):
    explanation=re.fullmatch(r'/api/bookings/([a-f0-9]{32})/videos/explanations',path)
    if explanation:
        if handler.command!='POST' or urlparse(handler.path).query:raise engine.BookingError(405,'Invalid explanation method')
        result=video_followup.explain(con,explanation[1],user,handler.body(),clock())
        con.commit();handler.reply(200,result);return True
    match = re.fullmatch(r'/api/bookings/([a-f0-9]{32})/videos(?:/([a-f0-9]{32})/(playback|poster))?',path)
    if not match:
        return False
    query = parse_qs(urlparse(handler.path).query,keep_blank_values=True)
    if any(len(v)!=1 for v in query.values()): raise ValueError('Duplicate video query')
    if handler.command == 'GET':
        if match[2]:
            if query: raise ValueError('Unexpected media query')
            download(handler,con,root,match[1],user,match[2],match[3])
        else:
            if set(query)-{'day'}: raise ValueError('Unexpected video query')
            handler.reply(200,overview(con,match[1],user,query.get('day',[None])[0],clock()))
        return True
    if handler.command != 'POST' or match[2]:
        raise engine.BookingError(405, 'Amal mavjud emas')
    if not _uploads.acquire(blocking=False):
        raise media.VideoUnavailable('Video xizmati band. Birozdan so‘ng qayta urining')
    try:
        return receive(handler,con,user,match,query,root,clock)
    finally:
        _uploads.release()


def receive(handler, con, user, match, query, root, clock):
    data = options({k:v[0] for k,v in query.items()})
    care.access(con,match[1],user)
    # Unknown old requests cannot bypass window/status checks or consume decoding.
    if not con.execute('SELECT 1 FROM booking_videos WHERE actor=? AND request_id=?',(user,data['requestId'])).fetchone():
        writable(con,match[1],user,data,clock())
    if handler.headers.get('Content-Type') not in ('video/mp4','video/quicktime','application/octet-stream'):
        raise engine.BookingError(415,'MP4/MOV video tanlang')
    length = handler.headers.get('Content-Length','')
    if not re.fullmatch(r'[0-9]{1,9}',length) or not 12 <= int(length) <= policy.MAX_BYTES:
        raise engine.BookingError(413,'Video 32 MiB dan oshmasin')
    if handler.headers.get('Transfer-Encoding'):
        raise ValueError('Chunked request not supported')
    engine.begin(con)
    conversations.quota(con,user,'video-upload',6)
    con.commit()
    upload_root = Path(root)/'care-videos'
    upload_root.mkdir(parents=True,exist_ok=True,mode=0o700)
    with tempfile.TemporaryDirectory(prefix='.upload-',dir=upload_root) as folder:
        source = Path(folder)/'source.mp4'
        with source.open('wb') as stream:
            remaining = int(length)
            deadline = time.monotonic()+60
            socket = getattr(handler,'connection',None)
            previous_timeout = socket.gettimeout() if socket else None
            try:
                while remaining:
                    left = deadline-time.monotonic()
                    if left <= 0: raise ValueError('Video upload timeout')
                    if socket: socket.settimeout(min(left,30))
                    read = getattr(handler.rfile,'read1',handler.rfile.read)
                    chunk = read(min(65536,remaining))
                    if not chunk: raise ValueError('Incomplete video upload')
                    stream.write(chunk); remaining -= len(chunk)
            except TimeoutError as error:
                raise engine.BookingError(408,'Yuklash vaqti tugadi. Qayta urinib ko‘ring') from error
            finally:
                if socket: socket.settimeout(previous_timeout)
        handler.reply(200,store(con,root,match[1],user,data,source,clock))
    return True
