import os


SECRET_KEY = os.environ.get('SECRET_KEY', 'devkey')
PREFERRED_URL_SCHEME = os.environ.get('PREFERRED_URL_SCHEME', 'http')

SEI_URL_BASE = os.environ.get('SEI_URL_BASE', 'https://sei.caveon.com')
SEI_ID = os.environ.get('SEI_ID')
SEI_SECRET = os.environ.get('SEI_SECRET')

REDIS_URL = os.environ.get('REDIS_URL', 'redis://redis:6379')
