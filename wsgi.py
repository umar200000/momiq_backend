"""WSGI transport for the shared API handlers; production uses Gunicorn."""
from email.message import Message
from http import HTTPStatus
from io import BytesIO
from server import Handler

class WsgiHandler(Handler):
    def __init__(self, environ):
        self.command = environ['REQUEST_METHOD']
        self.path = environ.get('PATH_INFO', '/')
        self.client_address = (environ.get('REMOTE_ADDR', ''), 0)
        self.headers = Message()
        for key, value in environ.items():
            if key.startswith('HTTP_'):
                self.headers[key[5:].replace('_', '-')] = value
        for key in ('CONTENT_LENGTH', 'CONTENT_TYPE'):
            if environ.get(key):
                self.headers[key.replace('_', '-')] = environ[key]
        self.rfile = environ['wsgi.input']
        self.wfile = BytesIO()
        self.response_headers = []
        self.response_status = 500

    def send_response(self, code, message=None):
        self.response_status = code
        self.response_headers = []

    def send_header(self, name, value):
        self.response_headers.append((name, value))

    def end_headers(self):
        pass

def application(environ, start_response):
    handler = WsgiHandler(environ)
    handler.dispatch()
    start_response(f'{handler.response_status} {HTTPStatus(handler.response_status).phrase}', handler.response_headers)
    return [handler.wfile.getvalue()]
