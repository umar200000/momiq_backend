"""Read-only checks for the API and admin origins serving this release."""
import json
import re
import sys
import argparse
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

API = 'https://api.momiq.net'
ADMIN = 'https://admin.momiq.net'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def verify(revision, *, admin_dir=None, admin_only=False):
    if not admin_only and not re.fullmatch('[0-9a-f]{40}', revision or ''):
        raise ValueError('Full commit required')
    if admin_only and admin_dir is None:
        raise ValueError('Pinned admin files required')
    opener = build_opener(NoRedirect())
    checks = []

    def get(base, path, status=200, json_body=True, headers=None):
        try:
            response = opener.open(Request(base + path, headers=headers or {}), timeout=10)
        except HTTPError as error:
            response = error
        with response:
            accepted=status if isinstance(status,tuple) else (status,)
            if response.status not in accepted:
                raise ValueError(f'{path[:70]} expected {status}, received {response.status}')
            raw = response.read(8*1024*1024+1)
            if len(raw)>8*1024*1024:
                raise ValueError('Response too large')
            checks.append((path[:70],response.status))
            if base==ADMIN and path=='/admin/':
                directives={tuple(part.split()) for part in response.headers.get('Content-Security-Policy','').split(';')}
                if not {('script-src',"'self'"),('frame-ancestors',"'none'")} <= directives:
                    raise ValueError('Missing admin script or frame restrictions')
            if not json_body:
                return raw
            if response.headers.get_content_type()!='application/json' or response.headers.get('Cache-Control')!='no-store':
                raise ValueError('Invalid API response headers')
            body=json.loads(raw)
            if not isinstance(body,dict) or (status in (400,401,414) and set(body)!={'error'}):
                raise ValueError('Invalid API response shape')
            return body

    def admin_assets():
        for path,name,marker in (('/admin/','index.html',b'loginForm'),('/admin/app.js','app.js',b'/api/admin/'),
                                 ('/admin/style.css','style.css',b'{')):
            raw=get(ADMIN,path,200,False)
            if marker not in raw or (admin_dir is not None and raw!=(admin_dir/name).read_bytes()):
                raise ValueError('Served admin asset differs from tested version: '+name)

    if admin_only:
        admin_assets()
        return {'checks':checks}
    for path in ('/api/health','/api/ready'):
        body=get(API,path)
        if body.get('ok') is not True or body.get('mode')!='production' or body.get('releaseSha')!=revision:
            raise ValueError('Unexpected release or database state')
        if path=='/api/ready' and type(body.get('schemaVersion')) is not int:
            raise ValueError('Missing database version')
    if not isinstance(get(API,'/api/sitters').get('sitters'),list):
        raise ValueError('Invalid public catalog')
    get(API,'/api/health?'+'&'.join(['q=1']*32))
    get(API,'/api/health?'+'&'.join(['q=1']*33),400)
    # Gunicorn can reject the request line before the application returns 414.
    get(API,'/api/health?q='+'x'*4096,(400,414),False)
    for path in ('/api/me','/api/me/listings','/api/messages'):
        get(API,path,401)
    get(ADMIN,'/api/admin/users',401)
    for base,path in ((API,'/api/me'),(ADMIN,'/api/admin/users')):
        for origin in ('https://foreign.invalid',base+'/extra'):
            get(base,path,403,headers={'Origin':origin})
    get(API,'/api/admin/users',404,False)
    get(ADMIN,'/api/me',404,False)
    admin_assets()
    return {'releaseSha':revision,'checks':checks}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('revision',nargs='?')
    parser.add_argument('--admin-dir',type=Path)
    parser.add_argument('--admin-only',action='store_true')
    args=parser.parse_args()
    print(json.dumps(verify(args.revision,admin_dir=args.admin_dir,admin_only=args.admin_only)))
