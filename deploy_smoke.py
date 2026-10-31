"""Read-only HTTP release checks. No login, cookies, booking or financial writes."""
import argparse
import hashlib
from http.client import HTTPException
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from release_pair import ASSETS
from deployment_health import MOBILE_FEATURES
from migrations import MIGRATIONS

MAX_RESPONSE = 8 * 1024 * 1024


class SmokeFailure(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def base_url(value):
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        raise SmokeFailure('Invalid origin port') from None
    if (parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment
            or parsed.path not in ('', '/') or not parsed.hostname or port == 0
            or any(c.isspace() for c in value)
            or parsed.scheme not in ('https', 'http')
            or (parsed.scheme == 'http' and parsed.hostname not in ('127.0.0.1', '::1'))):
        raise SmokeFailure('Use an HTTPS origin or numeric HTTP loopback without credentials or path')
    return value.rstrip('/')


def check(api_url, admin_url, revision, mode, admin_dir=None, *, mobile_release=False):
    api_url, admin_url = base_url(api_url), base_url(admin_url)
    if not re.fullmatch(r'[a-f0-9]{40}', revision):
        raise SmokeFailure('Expected full lowercase release SHA')
    if mode not in ('local', 'test', 'staging', 'production'):
        raise SmokeFailure('Invalid expected environment')
    opener = build_opener(ProxyHandler({}), NoRedirect())
    checks = []

    def fetch(name, base, path, status=200, headers=None, json_body=True):
        started = time.monotonic()
        request = Request(base + path, headers=headers or {}, method='GET')
        try:
            try:
                response = opener.open(request, timeout=3)
            except HTTPError as error:
                response = error
            with response:
                if response.status != status:
                    raise SmokeFailure(name + ': unexpected HTTP status ' + str(response.status))
                raw = response.read(MAX_RESPONSE + 1)
                if len(raw) > MAX_RESPONSE:
                    raise SmokeFailure(name + ': response limit exceeded')
                if status == 200 or status == 401:
                    if response.headers.get('X-Content-Type-Options') != 'nosniff':
                        raise SmokeFailure(name + ': missing nosniff')
                if json_body:
                    if response.headers.get_content_type() != 'application/json':
                        raise SmokeFailure(name + ': expected JSON')
                    if response.headers.get('Cache-Control') != 'no-store':
                        raise SmokeFailure(name + ': response may be cached')
                    try:
                        body = json.loads(raw)
                    except (ValueError, UnicodeError):
                        raise SmokeFailure(name + ': invalid JSON') from None
                    if not isinstance(body, dict):
                        raise SmokeFailure(name + ': expected JSON object')
                else:
                    body = raw
                checks.append({'check': name, 'status': status,
                               'durationMs': round((time.monotonic() - started) * 1000, 2)})
                return body, response.headers
        except (URLError, OSError, HTTPException):
            # Never print URLs, response data, proxy configuration or server errors.
            raise SmokeFailure(name + ': transport failed') from None

    health, _ = fetch('health', api_url, '/api/health')
    ready, _ = fetch('database-readiness', api_url, '/api/ready')
    for name, data in (('health', health), ('readiness', ready)):
        if data.get('ok') is not True or data.get('mode') != mode or data.get('releaseSha') != revision:
            raise SmokeFailure(name + ': wrong release or environment')
    if type(ready.get('schemaVersion')) is not int or ready['schemaVersion']!=MIGRATIONS[-1][0]:
        raise SmokeFailure('readiness: unexpected schema version for this release')
    if mode in ('production', 'staging'):
        if health.get('testLogin') is not False or (health.get('sms') is not True and
                                                    health.get('clientLoginEnabled') is not False):
            raise SmokeFailure('Hosted test login must be disabled')
    features=health.get('mobileFeatures')
    if not isinstance(features,list) or not all(feature in features for feature in MOBILE_FEATURES):
        raise SmokeFailure('Missing mobile API capabilities')
    if mobile_release and (mode!='production' or health.get('sms') is not True or
                           health.get('clientLoginEnabled') is not True):
        raise SmokeFailure('Production mobile login is unavailable')
    for service in ('boarding', 'homeVisit', 'personal'):
        data, _ = fetch('catalog-' + service, api_url, '/api/sitters?service=' + service + '&pet=cat')
        if (not isinstance(data.get('sitters'), list) or 'nextCursor' not in data
                or not isinstance(data.get('asOf'), str)):
            raise SmokeFailure('Invalid catalog page')
    for name, path in (('profile', '/api/me'), ('bookings', '/api/bookings'),
                       ('notifications', '/api/notifications'), ('profile-export','/api/me/profile-export'),
                       ('wallet','/api/wallet'),('conversations','/api/conversations'),('support','/api/support')):
        fetch('anonymous-' + name, api_url, path, status=401)
    fetch('invalid-bearer', api_url, '/api/me', status=401,
          headers={'Authorization': 'Bearer deployment-smoke-invalid'})
    fetch('anonymous-admin', admin_url, '/api/admin/users', status=401)
    fetch('invalid-admin-cookie', admin_url, '/api/admin/users', status=401,
          headers={'Cookie': 'momiq_admin=deployment-smoke-invalid'})
    if api_url != admin_url:
        fetch('public-admin-boundary', api_url, '/api/admin/users', status=404, json_body=False)
        fetch('admin-client-boundary', admin_url, '/api/me', status=404, json_body=False)
    for asset in ASSETS:
        raw, headers = fetch('admin-' + asset, admin_url,
                             '/admin/' if asset == 'index.html' else '/admin/' + asset, json_body=False)
        if not raw or "frame-ancestors 'none'" not in headers.get('Content-Security-Policy', ''):
            raise SmokeFailure('Missing admin asset or security policy: ' + asset)
        if admin_dir is not None:
            root = Path(admin_dir).resolve()
            expected = root / asset
            if not expected.resolve().is_relative_to(root):
                raise SmokeFailure('Admin asset escapes its release directory')
            if hashlib.sha256(raw).digest() != hashlib.sha256(expected.read_bytes()).digest():
                raise SmokeFailure('Served admin asset mismatch: ' + asset)
    return {'ok': True, 'releaseSha': revision, 'mode': mode, 'schemaVersion': ready['schemaVersion'],
            'mobileReleaseChecked':mobile_release, 'adminBytesVerified': admin_dir is not None, 'checks': checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-url', required=True)
    parser.add_argument('--admin-url', required=True)
    parser.add_argument('--backend-sha', required=True)
    parser.add_argument('--mode', required=True, choices=('local', 'test', 'staging', 'production'))
    parser.add_argument('--admin-dir', type=Path)
    parser.add_argument('--mobile-release',action='store_true',help='Also require production mobile login readiness')
    args = parser.parse_args()
    try:
        result = check(args.api_url, args.admin_url, args.backend_sha, args.mode, args.admin_dir,mobile_release=args.mobile_release)
    except (ValueError, OSError):
        # Fixed diagnostic: HTTP response bodies and configuration never enter CI logs.
        parser.exit(1, 'Release smoke failed; inspect restricted server diagnostics\n')
    print(json.dumps(result, separators=(',', ':')))


if __name__ == '__main__':
    main()
