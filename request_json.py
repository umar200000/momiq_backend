"""Bounded, unambiguous UTF-8 JSON bodies shared by local HTTP and WSGI."""
import json
import math
import re
import threading
import time

MAX_BYTES = 32_000_000
MAX_DEPTH = 64
READ_SECONDS = 60
_readers = threading.BoundedSemaphore(2)
_escaped_surrogate = re.compile(rb'\\u[dD][89a-fA-F]')
surrogates = re.compile(r'[\ud800-\udfff]')


class BodyError(Exception):
    def __init__(self,status,message):
        self.status,self.message=status,message


def _pairs(items):
    result={}
    for key,value in items:
        if key in result: raise ValueError('Duplicate JSON key')
        result[key]=value
    return result


def _constant(_):
    raise ValueError('Non-finite JSON number')


def _float(value):
    number=float(value)
    if not math.isfinite(number):raise ValueError('Non-finite JSON number')
    return number


def _check_unicode(value):
    if isinstance(value,str):
        if surrogates.search(value):
            raise ValueError('Invalid Unicode scalar')
    elif isinstance(value,dict):
        for key,item in value.items():
            _check_unicode(key)
            _check_unicode(item)
    elif isinstance(value,list):
        for item in value:
            _check_unicode(item)


def decode(raw):
    if len(raw)>MAX_BYTES:raise BodyError(413,'So‘rov juda katta')
    # Limit nesting before the recursive JSON decoder allocates containers.
    # Brackets and escaped quotes inside strings do not count as nesting.
    depth=0;quoted=False;escaped=False
    for byte in raw:
        if quoted:
            if escaped:escaped=False
            elif byte==92:escaped=True
            elif byte==34:quoted=False
        elif byte==34:quoted=True
        elif byte in (91,123):
            depth+=1
            if depth>MAX_DEPTH:raise ValueError('JSON nesting limit exceeded')
        elif byte in (93,125):depth-=1
    obj=json.loads(raw.decode('utf-8'),object_pairs_hook=_pairs,parse_constant=_constant,parse_float=_float)
    if not isinstance(obj,dict):raise ValueError('JSON object required')
    # Strict UTF-8 already excludes literal surrogates. JSON escapes can still
    # produce unpaired ones, even inside an array or an object key.
    if _escaped_surrogate.search(raw):
        _check_unicode(obj)
    return obj


def read(handler):
    lengths=handler.headers.get_all('Content-Length',[])
    if len(lengths)!=1 or not re.fullmatch(r'[0-9]{1,8}',lengths[0]):
        raise BodyError(400,'Content-Length noto‘g‘ri')
    size=int(lengths[0])
    if not 0<size<=MAX_BYTES:raise BodyError(413,'So‘rov hajmi noto‘g‘ri')
    if handler.headers.get('Transfer-Encoding') is not None:
        raise BodyError(400,'Transfer-Encoding qabul qilinmaydi')
    types=handler.headers.get_all('Content-Type',[])
    if len(types)!=1 or types[0].split(';',1)[0].strip().lower()!='application/json':
        raise BodyError(415,'JSON yuboring')
    if not _readers.acquire(timeout=1):raise BodyError(503,'So‘rovlar band. Qayta urining.')
    connection=None;restore_timeout=False
    try:
        connection=getattr(handler,'connection',None)
        timeout=connection.gettimeout() if connection else None
        restore_timeout=connection is not None
        deadline=time.monotonic()+READ_SECONDS
        raw=bytearray()
        while len(raw)<size:
            left=deadline-time.monotonic()
            if left<=0:raise TimeoutError()
            if connection:connection.settimeout(min(left,30))
            chunk=getattr(handler.rfile,'read1',handler.rfile.read)(min(65536,size-len(raw)))
            if time.monotonic()>deadline:raise TimeoutError()
            if not chunk:raise BodyError(400,'So‘rov to‘liq kelmadi')
            raw.extend(chunk)
        return decode(raw)
    except TimeoutError:
        raise BodyError(408,'So‘rovni yuborish vaqti tugadi') from None
    finally:
        try:
            if restore_timeout:
                try:connection.settimeout(timeout)
                except OSError:
                    # A peer/transport may close while the body is being read.
                    # Preserve its original result/error, but never reuse it.
                    handler.close_connection=True
        finally:
            # Socket inspection/restoration can fail too. Neither may leak a
            # bounded reader slot and turn subsequent requests into 503s.
            _readers.release()
