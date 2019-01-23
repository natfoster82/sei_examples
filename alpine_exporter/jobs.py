import codecs
from datetime import datetime
from json import dumps
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import paramiko
from rq.decorators import job

from helpers import redis_store, rq_store, get_integration_info, Exporter, MyFTP_TLS


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
        if sftp is not None:
            sftp.close()
        if transport is not None:
            transport.close()
        raise e


@job('default', connection=rq_store)
def upload_all():
    cron_ids = redis_store.smembers('cron_ids')
    for exam_id in cron_ids:
        upload_fresh_data.delay(exam_id)


@job('default', connection=rq_store)
def upload_fresh_data(exam_id):
    integration_info = get_integration_info(exam_id)

    start = integration_info.get('last_timestamp')
    end = datetime.utcnow().isoformat()
    exporter = Exporter(exam_id, integration_info, 'all', start, end)

    cand_filename = 'cand-' + exporter.filename
    exam_filename = 'exam-' + exporter.filename
    zip_filename = exam_id + '-' + exporter.filename.split('.')[0] + '.zip'

    with TemporaryDirectory() as tempdirname:
        cand_path = '{0}/{1}'.format(tempdirname, cand_filename)
        exam_path = '{0}/{1}'.format(tempdirname, exam_filename)
        zip_path = '{0}/{1}'.format(tempdirname, zip_filename)
        with ZipFile(zip_path, 'w') as zip_file:
            with codecs.open(cand_path, 'w', encoding='utf-8-sig') as cand_file, codecs.open(exam_path, 'w', encoding='utf-8-sig') as exam_file:
                for l in exporter.generate():
                    cand_l = l[:exporter.split_idx]
                    exam_l = l[exporter.split_idx:]
                    cand_file.write(exporter.make_row(cand_l))
                    exam_file.write(exporter.make_row(exam_l))
            zip_file.write(cand_path, cand_filename)
            zip_file.write(exam_path, exam_filename)
        with MyFTP_TLS() as ftp:
            ftp.connect(integration_info['sftp_host'], integration_info.get('sftp_port') or 21)
            ftp.login(integration_info['sftp_user'], integration_info['sftp_password'])
            ftp.prot_p()
            with open(zip_path, 'rb') as zip_file:
                try:
                    ftp.storbinary('STOR ' + integration_info['sftp_path'] + zip_filename, zip_file, 1024)
                except OSError:
                    pass
    if exporter.last_timestamp:
        integration_info['last_timestamp'] = exporter.last_timestamp
    redis_store.set(exam_id, dumps(integration_info))
