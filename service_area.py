"""Check service points against a locally supplied, pinned 2D GeoJSON boundary."""
import hashlib
import json
import math
from pathlib import Path
import re


class AreaUnavailable(Exception):
    pass


class OutsideArea(ValueError):
    pass


def load(env):
    filename, pin = env.get('MOMIQ_AREA_FILE'), env.get('MOMIQ_AREA_SHA256')
    if filename is None and pin is None:
        return None
    if not filename or not Path(filename).is_absolute() or not re.fullmatch('[0-9a-f]{64}',pin or ''):
        raise ValueError('Service area requires an absolute geometry file and SHA-256')
    with Path(filename).open('rb') as stream:
        raw = stream.read(4*1024*1024+1)
    if len(raw) > 4*1024*1024 or hashlib.sha256(raw).hexdigest() != pin:
        raise ValueError('Service area file size or digest mismatch')
    geometry = json.loads(raw)
    if isinstance(geometry,dict) and geometry.get('type') == 'Feature':
        geometry = geometry.get('geometry')
    if not isinstance(geometry,dict) or geometry.get('type') not in ('Polygon','MultiPolygon'):
        raise ValueError('Expected a Polygon or MultiPolygon')
    polygons = geometry.get('coordinates')
    if geometry['type'] == 'Polygon':
        polygons = [polygons]
    if not isinstance(polygons, list) or not polygons:
        raise ValueError('Empty service area')
    area = []
    for polygon in polygons:
        if not isinstance(polygon,list) or not polygon:
            raise ValueError('Empty polygon')
        rings = []
        for ring in polygon:
            if not isinstance(ring,list) or len(ring)<4 or ring[0]!=ring[-1]:
                raise ValueError('Open or empty service area ring')
            for point in ring:
                if (not isinstance(point,list) or len(point)!=2 or
                        any(type(v) not in (int,float) for v in point) or
                        not -180 <= point[0] <= 180 or not -90 <= point[1] <= 90):
                    raise ValueError('Invalid longitude/latitude in service area')
            edges = tuple(zip(ring,ring[1:]))
            if not math.fsum(a[0]*b[1]-a[1]*b[0] for a,b in edges):
                raise ValueError('Degenerate service area ring')
            xs,ys = zip(*ring)
            rings.append(((min(xs),min(ys),max(xs),max(ys)),edges))
        area.append(rings)
    return area


def ring_position(ring, x, y):
    bounds, edges = ring
    if not (bounds[0]<=x<=bounds[2] and bounds[1]<=y<=bounds[3]):
        return -1
    inside = False
    for (ax,ay),(bx,by) in edges:
        cross = (x-ax)*(by-ay) - (y-ay)*(bx-ax)
        if abs(cross) <= 1e-12 and min(ax,bx)<=x<=max(ax,bx) and min(ay,by)<=y<=max(ay,by):
            return 0
        if (ay>y)!=(by>y) and (cross<0)==(by>ay):
            inside = not inside
    return 1 if inside else -1


def require(area, location, environment):
    if area is None:
        if environment in ('production','staging'):
            raise AreaUnavailable('Xizmat hududi hali sozlanmagan')
        return
    x,y = location['lon'],location['lat']
    for outer,*holes in area:
        if ring_position(outer,x,y)>=0 and not any(ring_position(h,x,y)>0 for h in holes):
            return
    raise OutsideArea('Manzil Toshkent xizmat hududidan tashqarida')


def changed_addresses(area, previous, account, environment):
    before = {a['id']:a for a in previous.get('addresses',[])}
    for address in account.get('addresses',[]):
        original = before.get(address['id'])
        if original is None or any(original.get(k) != address.get(k) for k in ('lat','lon','address')):
            require(area,address,environment)
