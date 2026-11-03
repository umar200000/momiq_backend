"""Read-only checks for the API and admin origins serving this release."""
import json
import re
import sys
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, build_opener

API = 'https://api.momiq.net'
ADMIN = 'https://admin.momiq.net'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def verify(revision):
    if not re.fullmatch('[0-9a-f]{40}', revision):
        raise ValueError('Full commit required')
    opener = build_opener(NoRedirect())
    checks = []

    def get(base, path, status=200, json_body=True):
        try:
            response = opener.open(base + path, timeout=10)
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
            if not json_body:
                return raw
            if response.headers.get_content_type()!='application/json' or response.headers.get('Cache-Control')!='no-store':
                raise ValueError('Invalid API response headers')
            body=json.loads(raw)
            if not isinstance(body,dict) or (status in (400,401,414) and set(body)!={'error'}):
                raise ValueError('Invalid API response shape')
            return body

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
    get(API,'/api/admin/users',404,False)
    get(ADMIN,'/api/me',404,False)
    for path,marker in (('/admin/',b'loginForm'),('/admin/app.js',b'/api/admin/'),('/admin/style.css',b'{')):
        if marker not in get(ADMIN,path,200,False):
            raise ValueError('Unexpected admin asset: '+path)
    return {'releaseSha':revision,'checks':checks}


if __name__=='__main__':
    print(json.dumps(verify(sys.argv[1])))
