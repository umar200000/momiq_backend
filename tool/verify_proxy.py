"""Run the repository's Nginx, TLS and Gunicorn paths on ephemeral loopback ports."""
from contextlib import ExitStack
import http.client
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

ROOT = Path(__file__).resolve().parents[1]


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


def stop(process):
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def verify():
    api,admin = 'api.momiq.net','admin.momiq.net'
    with TemporaryDirectory(prefix='momiq-proxy-test-') as tmp, ExitStack() as stack:
        root = Path(tmp)
        frontend,backend = port(),port()
        while frontend==backend:
            backend=port()
        cert,key = root/'cert.pem',root/'key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=127.0.0.1',
                        '-addext','subjectAltName=IP:127.0.0.1','-keyout',str(key),'-out',str(cert)],
                       check=True,capture_output=True)
        password = secrets.token_urlsafe(30)
        assets = root/'assets'
        assets.mkdir()
        (assets/'index.html').write_text('TEST')
        env = {**os.environ,'MOMIQ_ENV':'production','MOMIQ_ALLOW_TEST_LOGIN':'0','MOMIQ_ADMIN_PASSWORD':password,
               'MOMIQ_DATA_DIR':str(root/'data'),'MOMIQ_ADMIN_DIR':str(assets)}
        for name in ('MOMIQ_AREA_FILE','MOMIQ_AREA_SHA256'):
            env.pop(name,None)
        subprocess.run([sys.executable,'-c','import server; server.setup()'],cwd=ROOT,env=env,check=True)
        gunicorn = subprocess.Popen([sys.executable,'-m','gunicorn','--bind',f'127.0.0.1:{backend}',
                                     '--config','gunicorn.conf.py','wsgi:application'],cwd=ROOT,env=env,
                                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        stack.callback(stop,gunicorn)
        conf = (ROOT/'deploy/nginx.conf').read_text().replace('listen 80;',f'listen 127.0.0.1:{frontend} ssl;')
        conf = conf.replace('/var/log/nginx/momiq-access.log',str(root/'access.log'))
        conf = conf.replace('/etc/nginx/snippets/momiq-proxy.conf',str(root/'proxy.conf'))
        snippet = (ROOT/'deploy/momiq-proxy.conf').read_text().replace('127.0.0.1:8080',f'127.0.0.1:{backend}')
        (root/'proxy.conf').write_text(snippet)
        paths = '\n'.join(f'{name}_temp_path {root}/{name};' for name in ('client_body','proxy','fastcgi','scgi','uwsgi'))
        (root/'nginx.conf').write_text(f'daemon off; master_process off; pid {root}/pid; error_log {root}/errors.log;\n'
                                       f'events {{}} http {{ ssl_certificate {cert}; ssl_certificate_key {key};\n'
                                       +paths+'\n'+conf+'\n}')
        nginx = subprocess.Popen([shutil.which('nginx') or '/usr/sbin/nginx','-p',str(root),'-c',str(root/'nginx.conf')],
                                 stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        stack.callback(stop,nginx)
        tls = ssl.create_default_context(cafile=str(cert))
        def call(host,path,method='GET',body=None,headers=None):
            conn = http.client.HTTPSConnection('127.0.0.1',frontend,context=tls,timeout=5)
            try:
                conn.request(method,path,json.dumps(body).encode() if body is not None else None,
                             {'Host':host,'Content-Type':'application/json',**(headers or {})})
                response = conn.getresponse()
                return response.status,response.headers,response.read()
            finally:
                conn.close()
        deadline = time.monotonic()+20
        while time.monotonic()<deadline:
            if nginx.poll() is not None or gunicorn.poll() is not None:
                raise RuntimeError('Proxy fixture process exited during startup')
            try:
                if call(api,'/api/ready')[0]==200:
                    break
            except (OSError,http.client.HTTPException):
                pass
            time.sleep(.1)
        else:
            raise RuntimeError('Proxy fixture readiness timeout')
        assert call(api,'/api/admin/users')[0]==404
        assert call(admin,'/api/me')[0]==404
        assert call(api,'/api/me?TEST_PRIVATE_MARKER=1')[0]==401
        assert call(admin,'/api/admin/me',headers={'Origin':'https://foreign.invalid'})[0]==403
        assert call(admin,'/api/admin/me',headers={'Origin':'https://'+admin+'/not-an-origin'})[0]==403
        assert call(api,'/api/me','POST',headers={'Content-Length':str(33*1024*1024)})[0]==413
        payload = {'username':'admin','password':password}
        status,headers,_ = call(admin,'/api/admin/login','POST',payload,{'Origin':'https://'+admin})
        assert status==200
        cookie = headers['Set-Cookie']
        assert all(attr in cookie for attr in ('; Secure','HttpOnly','SameSite=Strict','Path=/api/admin'))
        session = {'Cookie':cookie.split(';')[0]}
        assert call(admin,'/api/admin/me',headers=session)[0]==200
        assert call(admin,'/api/admin/logout','POST',{},session)[0]==200
        assert call(admin,'/api/admin/me',headers=session)[0]==401
        # Incoming forged client-IP headers cannot bypass the edge request limit.
        replies = [call(admin,'/api/admin/login','POST',{'username':'TEST','password':'wrong'},
                        {'X-Real-IP':f'198.51.100.{i}'})[0] for i in range(8)]
        assert 401 in replies and 429 in replies
        log = (root/'access.log').read_text()
        assert log.strip() and all(secret not in log for secret in (password,session['Cookie'],'TEST_PRIVATE_MARKER','/api/'))
        print('Loopback TLS, readiness, host isolation, CSRF, size, cookie, revocation, rate limit and private access log passed')


if __name__=='__main__':
    verify()
