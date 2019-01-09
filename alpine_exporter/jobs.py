from rq.decorators import job
from app import redis_store


@job('default', connection=redis_store)
def test_worker():
    print('CONSIDER THIS WORKER TESTED')
