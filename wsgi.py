"""WSGI transport for the shared API handlers; production uses Gunicorn."""
from email.message import Message
from http import HTTPStatus
from io import BytesIO
import os
from server import Handler


class FileRange:
    """Hold the already authorized descriptor, never reopen a private path."""
    def __init__(self, stream, length):
        self.stream = os.fdopen(os.dup(stream.fileno()),'rb')
        self.remaining = length

    def __iter__(self):
        return self

    def __next__(self):
        if self.remaining == 0 or self.stream.closed:
            self.close()
            raise StopIteration
        try:
            chunk = self.stream.read(min(self.remaining,65536))
            if not chunk:
                raise OSError('Incomplete private media range')
            self.remaining -= len(chunk)
            return chunk
        except BaseException:
            self.close()
            raise

    def close(self):
        self.stream.close()


class WsgiHandler(Handler):
    def __init__(self, environ):
        self.command = environ['REQUEST_METHOD']
        self.path = environ.get('PATH_INFO', '/')
        if environ.get('QUERY_STRING'):
            self.path += '?' + environ['QUERY_STRING']
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
        self.file_range = None

    def send_file_range(self, stream, start, length):
        self.file_range = FileRange(stream,length)
        self.file_range.stream.seek(start)

    def send_response(self, code, message=None):
        if self.file_range is not None:
            self.file_range.close()
            self.file_range = None
        self._dispatch_status = code
        self.response_status = code
        self.response_headers = []

    def send_header(self, name, value):
        self.response_headers.append((name, value))

    def end_headers(self):
        pass

def application(environ, start_response):
    handler = WsgiHandler(environ)
    handler.dispatch()
    try:
        start_response(f'{handler.response_status} {HTTPStatus(handler.response_status).phrase}', handler.response_headers)
    except BaseException:
        if handler.file_range is not None:
            handler.file_range.close()
        raise
    if handler.file_range is not None:
        return handler.file_range
    return [handler.wfile.getvalue()]
