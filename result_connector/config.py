import os


SECRET_KEY = os.environ.get('SECRET_KEY', 'devkey')
PREFERRED_URL_SCHEME = os.environ.get('PREFERRED_URL_SCHEME', 'http')

SEI_URL_BASE = os.environ.get('SEI_URL_BASE', 'https://sei.caveon.com')
SEI_ID = os.environ.get('SEI_ID')
SEI_SECRET = os.environ.get('SEI_SECRET')

REDIS_URL = os.environ.get('REDIS_URL', 'redis://redis:6379')
REDIS_DB = int(os.environ.get('REDIS_DB', '3'))

SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')
SLACK_CHANNEL = os.environ.get('SLACK_CHANNEL')
