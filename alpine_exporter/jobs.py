from rq.decorators import job
from app import redis_store, rq_store, get_integration_info
import paramiko
from datetime import datetime


def create_sftp_client(host, port, user, password):
    sftp = None
    transport = None
    try:
        # Create Transport object using supplied method of authentication.
        port = port or 22
        transport = paramiko.Transport((host, port))
        transport.connect(username=user, password=password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        return sftp
    except Exception as e:
        print('An error occurred creating SFTP client: %s: %s' % (e.__class__, e))
        if sftp is not None:
            sftp.close()
        if transport is not None:
            transport.close()
        pass


@job('default', connection=rq_store)
def upload_all():
    cron_ids = redis_store.smembers('cron_ids')
    for exam_id in cron_ids:
        upload_fresh_data.delay(exam_id)


@job('default', connection=rq_store)
def upload_fresh_data(exam_id):
    integration_info = get_integration_info(exam_id)
    sftp_client = create_sftp_client(integration_info['sftp_host'],
                                     integration_info['sftp_port'],
                                     integration_info['sftp_user'],
                                     integration_info['sftp_password'])
    sftp_client.put('testfile.txt', 'uploads/' + datetime.utcnow().isoformat() + '.txt')
    sftp_client.close()
