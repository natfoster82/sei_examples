from rq_scheduler import Scheduler

from helpers import rq_store
from jobs import upload_all

TEST_WORKER_INTERVAL = 60

if __name__ == '__main__':
    scheduler = Scheduler(connection=rq_store, interval=60.0)

    list_of_job_instances = scheduler.get_jobs()
    for job in list_of_job_instances:
        scheduler.cancel(job)

    schedule_delete_staged_files = scheduler.cron(
        cron_string='0 16 * * *',
        func=upload_all,
        args=[],
        kwargs={},
        repeat=None
    )

    scheduler.run()
