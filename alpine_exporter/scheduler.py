from datetime import datetime

from rq_scheduler import Scheduler

from app import rq_store
from jobs import test_worker

TEST_WORKER_INTERVAL = 60

if __name__ == '__main__':
    scheduler = Scheduler(connection=rq_store, interval=60.0)

    list_of_job_instances = scheduler.get_jobs()
    for job in list_of_job_instances:
        scheduler.cancel(job)

    schedule_test_worker = scheduler.schedule(
        scheduled_time=datetime.utcnow(),
        func=test_worker,
        args=[],
        kwargs={},
        interval=TEST_WORKER_INTERVAL,
        repeat=None,
        result_ttl=TEST_WORKER_INTERVAL * 10
    )

    scheduler.run()
