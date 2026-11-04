"""Limit Gunicorn access logs to status, response length and duration."""
access_log_format = '%(s)s %(b)s %(L)s'
