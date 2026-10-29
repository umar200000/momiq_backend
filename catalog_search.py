"""Public discovery filters and stable, filter-bound keyset pages."""
import base64
from datetime import datetime, timezone
import hashlib
import json
import heapq
import itertools
import math
import re

import booking_capacity
import catalog
import sitter_availability

PAGE_SIZE = 20


def options(params, user=None):
    allowed={'service','pet','minPrice','maxPrice','animals','verified','q','minRating','startsAt','endsAt','after','favorites','lat','lon','region','maxDistance'}
    if set(params)-allowed or any(len(v)!=1 for v in params.values()):
        raise ValueError('Qidiruv parametrlari noto‘g‘ri yoki takrorlangan')
    raw={k:v[0] for k,v in params.items()}
    if raw.get('region','tashkent')!='tashkent':raise ValueError('Hozir faqat Toshkent hududi mavjud')
    if ('lat' in raw)!=('lon' in raw):raise ValueError('Ikkala koordinata kerak')
    def decimal(key,maximum):
        try:value=float(raw[key])
        except (ValueError,OverflowError):raise ValueError('Koordinata yoki masofa noto‘g‘ri')
        if not math.isfinite(value) or abs(value)>maximum:raise ValueError('Koordinata yoki masofa noto‘g‘ri')
        return value
    origin=[round(decimal('lat',90),2),round(decimal('lon',180),2)] if 'lat' in raw else None
    distance=decimal('maxDistance',50) if 'maxDistance' in raw else None
    if distance is not None and (distance<1 or origin is None):raise ValueError('Masofa filtri uchun joylashuv kerak')
    service=raw.get('service')
    pet=raw.get('pet')
    if service is not None and service not in catalog.SERVICES:raise ValueError('Xizmat noto‘g‘ri')
    if pet is not None and pet not in catalog.PET_LABELS:raise ValueError('Hayvon turi noto‘g‘ri')
    def integer(key,default,minimum,maximum):
        value=raw.get(key)
        if value is None:return default
        if not re.fullmatch(r'\d{1,9}',value) or not minimum<=int(value)<=maximum:raise ValueError('Qidiruv chegarasi noto‘g‘ri')
        return int(value)
    minimum=integer('minPrice',0,0,999999999)
    maximum=integer('maxPrice',999999999,0,999999999)
    if minimum>maximum:raise ValueError('Narx oralig‘i noto‘g‘ri')
    animals=integer('animals',1,1,30)
    if raw.get('verified','0') not in ('0','1'):raise ValueError('Tasdiq filtri noto‘g‘ri')
    if raw.get('favorites','0') not in ('0','1'):raise ValueError('Saqlanganlar filtri noto‘g‘ri')
    if raw.get('favorites')=='1' and user is None:raise ValueError('Saqlanganlar uchun hisobga kiring')
    if raw.get('minRating','0') not in ('0','4.8'):raise ValueError('Reyting filtri noto‘g‘ri')
    query=raw.get('q','').strip()
    if len(query)>100:raise ValueError('Qidiruv matni juda uzun')
    interval=sitter_availability.interval(params)
    if interval and interval[0]<=datetime.now(timezone.utc):raise ValueError('Kelajakdagi sanani tanlang')
    normalized={'origin':origin,'maxDistance':distance,'region':'tashkent','service':service,'pet':pet,'minPrice':minimum,'maxPrice':maximum,'animals':animals,
                'verified':raw.get('verified','0')=='1','minRating':float(raw.get('minRating','0')),'q':query.casefold(),
                'interval':[booking_capacity.stamp(t) for t in interval] if interval else None,
                'favoritesOwner':user if raw.get('favorites')=='1' else None}
    digest=hashlib.sha256(json.dumps(normalized,sort_keys=True).encode()).hexdigest()[:24]
    after=None
    if 'after' in raw:
        token=raw['after']
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,512}',token):raise ValueError('Sahifa belgisi noto‘g‘ri')
        try:cursor=json.loads(base64.urlsafe_b64decode(token+'='*(-len(token)%4)))
        except (ValueError,UnicodeDecodeError) as error:raise ValueError('Sahifa belgisi noto‘g‘ri') from error
        keys={'last','query','distance'} if origin else {'last','query'}
        if (not isinstance(cursor,dict) or set(cursor)!=keys or cursor['query']!=digest
                or not isinstance(cursor['last'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}:(boarding|homeVisit|personal)',cursor['last'])):
            raise ValueError('Filtr o‘zgargan; qidiruvni boshidan boshlang')
        if origin and (type(cursor['distance']) not in (int,float) or not math.isfinite(cursor['distance']) or not 0<=cursor['distance']<=21000):
            raise ValueError('Sahifa masofasi noto‘g‘ri')
        after=cursor
    return normalized,interval,digest,after


def distance_km(origin, location):
    """Use only public, quantized discovery points; never private home coordinates."""
    if not origin or not location:return None
    lat1,lon1,lat2,lon2=map(math.radians,(*origin,location['lat'],location['lon']))
    value=math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return round(6371.0088*2*math.asin(math.sqrt(min(1,max(0,value)))),1)


def proximity_key(item):
    return (item['distance'] if item['distance'] is not None else 21000,*item['id'].split(':',1))


def page(con, environment, params, *, user=None):
    selected,interval,digest,after=options(params,user)
    if not con.in_transaction:con.execute('BEGIN')
    now=datetime.now(timezone.utc)
    favorites=None
    if selected['favoritesOwner']:
        row=con.execute('SELECT account FROM users WHERE id=?',(user,)).fetchone()
        favorites=set(json.loads(row[0]).get('favorites',[])) if row else set()
    def matches():
        for item in catalog.iter_profiles(con,environment,interval=interval,after=after['last'] if after and not selected['origin'] else '',service=selected['service']):
            if favorites is not None and item['id'] not in favorites:continue
            service=catalog.SERVICES[item['service']]
            if selected['service'] is not None and service!=selected['service']:continue
            if selected['pet'] is not None and catalog.PET_LABELS[selected['pet']] not in item['pets']:continue
            if not selected['minPrice']<=item['price']<=selected['maxPrice']:continue
            if selected['verified'] and not item['identityVerified']:continue
            if item['rating']<selected['minRating'] or selected['q'] not in item['name'].casefold():continue
            capacity=30 if service=='homeVisit' else item['capacity']
            if capacity<selected['animals']:continue
            if interval:
                free=booking_capacity.remaining(con,item['userId'],service,*interval,capacity,now)
                if free<selected['animals']:continue
                item.update(availabilityKnown=True,freeCapacity=free,
                            availabilityInterval={'startsAt':booking_capacity.stamp(interval[0]),'endsAt':booking_capacity.stamp(interval[1])})
            item['distance']=distance_km(selected['origin'],item['location'])
            item['distanceApproximate']=item['distance'] is not None
            # Unknown origins remain discoverable; this is a customer preference,
            # never a sitter service-radius or booking eligibility rule.
            if selected['maxDistance'] is not None and item['distance'] is not None and item['distance']>selected['maxDistance']:continue
            if selected['origin'] and after and proximity_key(item)<=(after['distance'],*after['last'].split(':',1)):continue
            yield item
    if selected['origin']:
        result=heapq.nsmallest(PAGE_SIZE+1,matches(),key=proximity_key)
    else:
        result=list(itertools.islice(matches(),PAGE_SIZE+1))
    more=len(result)>PAGE_SIZE
    result=result[:PAGE_SIZE]
    cursor=None
    if more:
        position={'last':result[-1]['id'],'query':digest}
        if selected['origin']:position['distance']=proximity_key(result[-1])[0]
        cursor=base64.urlsafe_b64encode(json.dumps(position,separators=(',',':')).encode()).decode().rstrip('=')
    return {'sitters':result,'nextCursor':cursor,'asOf':now.isoformat()}
