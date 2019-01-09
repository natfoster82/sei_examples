from rq import Worker, Queue, Connection
from app import app, rq_store


if __name__ == '__main__':
    with app.app_context():
        with Connection(rq_store):
            worker = Worker(map(Queue, app.config['QUEUES']))
            worker.work()
