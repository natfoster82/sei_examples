from datetime import datetime
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import paramiko
from dateutil.parser import parse
from rq.decorators import job

from helpers import redis_store, rq_store, get_integration_info, Exporter


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
    last_timestamp = integration_info.get('last_timestamp')
    if last_timestamp:
        start = parse(last_timestamp)
    else:
        start = None
    end = datetime.utcnow()
    exporter = Exporter(exam_id, integration_info, 'all', start, end)

    cand_filename = 'cand-' + exporter.filename
    exam_filename = 'exam-' + exporter.filename
    zip_filename = exam_id + '-' + exporter.filename[:11] + '.zip'

    with TemporaryDirectory() as tempdirname:
        cand_path = '{0}/{1}'.format(tempdirname, cand_filename)
        exam_path = '{0}/{1}'.format(tempdirname, exam_filename)
        zip_path = '{0}/{1}'.format(tempdirname, zip_filename)
        with ZipFile(zip_path, 'w') as zip_file:
            with open(cand_path, 'w') as cand_file, open(exam_path, 'w') as exam_file:
                for l in exporter.generate():
                    cand_l = l[:exporter.split_idx]
                    exam_l = l[exporter.split_idx:]
                    cand_file.write(exporter.make_row(cand_l))
                    exam_file.write(exporter.make_row(exam_l))
            zip_file.write(cand_path, cand_filename)
            zip_file.write(exam_path, exam_filename)
        sftp_client.put(zip_path, 'uploads/' + zip_filename)
    # TODO: write exporter.last_timestamp to redis
    sftp_client.close()
