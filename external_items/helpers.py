from redis import StrictRedis
from config import REDIS_URL, SECRET_KEY, SEI_URL_BASE, SEI_ID, SEI_SECRET
from itsdangerous import URLSafeTimedSerializer
import requests
from requests.auth import HTTPBasicAuth
from json import loads, dumps


redis_store = StrictRedis.from_url(REDIS_URL, db=4, decode_responses=True)
external_serializer = URLSafeTimedSerializer(SECRET_KEY)


def get_integration_info(exam_id):
    data = redis_store.get(exam_id)
    if data:
        return loads(data)
    url = SEI_URL_BASE + '/api/integrations/' + exam_id + '/credentials'
    resp = requests.get(url, auth=HTTPBasicAuth(username=SEI_ID, password=SEI_SECRET))
    if resp.status_code != 200:
        raise ValueError('No access to this exam_id')
    data = resp.json()
    redis_store.set(data['exam_id'], dumps(data))
    return data
