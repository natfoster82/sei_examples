import io
from datetime import datetime, timedelta
from json import loads, dumps
from multiprocessing.dummy import Pool as ThreadPool

import requests
import jwt
import paramiko
from flask import Flask, render_template, request, abort, jsonify, redirect, url_for
from flask_wtf import FlaskForm
from redis import StrictRedis
from requests.auth import HTTPBasicAuth
from werkzeug.contrib.fixers import ProxyFix
from wtforms import StringField, IntegerField
from wtforms.validators import Optional, ValidationError


# app setup
app = Flask(__name__)
app.config.from_pyfile('config.py')
if app.config['PREFERRED_URL_SCHEME'] == 'https':
    app.wsgi_app = ProxyFix(app.wsgi_app)

app.url_map.strict_slashes = False

# some helpers
redis_store = StrictRedis.from_url(app.config['REDIS_URL'], db=app.config['REDIS_DB'], decode_responses=True)
pool = ThreadPool(4)


def get_integration_info(exam_id):
    data = redis_store.get(exam_id)
    if data:
        return loads(data)
    url = app.config['SEI_URL_BASE'] + '/api/integrations/' + exam_id + '/credentials'
    resp = requests.get(url, auth=HTTPBasicAuth(username=app.config['SEI_ID'], password=app.config['SEI_SECRET']))
    if resp.status_code != 200:
        raise ValueError('No access to this exam_id')
    data = resp.json()
    redis_store.set(data['exam_id'], dumps(data))
    return data


class ConfigureForm(FlaskForm):
    sftp_host = StringField('SFTP Host')
    sftp_port = IntegerField('SFTP Port', default=22)
    sftp_user = StringField('SFTP User')
    sftp_password = StringField('SFTP Password')
    sftp_path = StringField('SFTP Path')

    def validate_sftp_path(self, field):
        if field.data and not field.data.endswith('/'):
            raise ValidationError('Must end with /')


def build_columns_and_data(delivery_json):
    columns = ['Delivery ID', 'Date']
    data = [delivery_json['id'], delivery_json['modified_at']]
    for key in sorted(delivery_json['examinee']['info']):
        columns.append(key)
        data.append(delivery_json['examinee']['info'][key])
    columns += [
        'Exam Name',
        'Score',
        'Passed',
        'Points Earned',
        'Points Available',
        'Duration',
        'Form',
        'Form ID',
        'Form Version ID'
    ]
    data += [
        delivery_json['exam']['name'],
        str(delivery_json['score']),
        str(delivery_json['passed']),
        str(delivery_json['points_earned']),
        str(delivery_json['points_available']),
        str(delivery_json['used_seconds']),
        delivery_json['form']['name'],
        delivery_json['form_id'],
        delivery_json['form_version_id']
    ]
    return columns, data


# views
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/sei_redirect')
def sei_redirect():
    confirm_token = request.args.get('confirm_token')
    if not confirm_token:
        abort(400)
    url = app.config['SEI_URL_BASE'] + '/api/integrations/confirm/' + confirm_token
    resp = requests.get(url, auth=HTTPBasicAuth(username=app.config['SEI_ID'], password=app.config['SEI_SECRET']))
    if resp.status_code != 200:
        abort(400)
    data = resp.json()
    exam_id = data['exam_id']
    secret = data['secret']
    existing_data = redis_store.get(exam_id)
    if existing_data:
        existing_data = loads(existing_data)
        existing_data.update(data)
        data = existing_data
    redis_store.set(exam_id, dumps(data))
    now = datetime.utcnow()
    exp_seconds = 3600
    exp_time = (now + timedelta(seconds=exp_seconds))
    payload = {'iss': 'SEI', 'sub': exam_id, 'iat': now, 'exp': exp_time}
    token = jwt.encode(payload, secret, algorithm='HS256').decode()
    return redirect(url_for('configure', jwt=token, exam_id=exam_id))


@app.route('/delivery_completed', methods=['POST'])
def delivery_completed():
    # authorize the request

    body = request.get_json()
    exam_id = body['exam_id']
    integration_info = get_integration_info(exam_id)
    auth_header = request.headers.get('Authorization')
    token = auth_header.split()[1]
    try:
        decoded = jwt.decode(token, integration_info['secret'], algorithms=['HS256'])
    except jwt.exceptions.InvalidTokenError:
        return jsonify(), 403

    sftp_host = integration_info.get('sftp_host')
    if not sftp_host:
        return jsonify(), 403

    # get full delivery object from SEI
    delivery_id = body['delivery_id']
    delivery_url = '{0}/api/exams/{1}/deliveries/{2}?include=exam,form'.format(app.config['SEI_URL_BASE'], exam_id, delivery_id)
    delivery_headers = {'Authorization': 'Bearer {0}'.format(integration_info['token'])}
    delivery_response = requests.get(delivery_url, headers=delivery_headers)
    delivery_json = delivery_response.json()

    # format the data into lists
    columns, data = build_columns_and_data(delivery_json)

    # write the lists to a tab delimited string
    output_str = '\t'.join(columns) + '\n' + '\t'.join(data) + '\n'
    output_file = io.StringIO(output_str)

    filename = '{}-{}.txt'.format(delivery_id, datetime.utcnow().isoformat())

    sftp_path = integration_info.get('sftp_path', '')
    if sftp_path:
        sftp_path.strip('/')
        filename = '{}/{}'.format(sftp_path, filename)

    sftp_user = integration_info.get('sftp_user')
    sftp_password = integration_info.get('sftp_password')
    sftp_port = integration_info.get('sftp_port') or 22

    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh_client.connect(hostname=sftp_host, username=sftp_user, password=sftp_password, port=sftp_port)

    ftp_client = ssh_client.open_sftp()
    ftp_client.putfo(output_file, filename)
    ftp_client.close()
    ssh_client.close()

    return jsonify()


@app.route('/delivery_widget')
def delivery_widget():
    exam_id = request.args.get('exam_id')
    delivery_id = request.args.get('delivery_id')
    token = request.args.get('jwt')
    integration_info = get_integration_info(exam_id)
    try:
        decoded = jwt.decode(token, integration_info['secret'], algorithms=['HS256'])
    except jwt.exceptions.InvalidTokenError:
        abort(403)
    configs = integration_info.get('configs', [])
    configs_by_event = {}
    for config in configs:
        try:
            configs_by_event[config['event']].append(config)
        except KeyError:
            configs_by_event[config['event']] = [config]
    return render_template('delivery_widget.html', exam_id=exam_id, delivery_id=delivery_id, token=token, configs_by_event=configs_by_event)


@app.route('/configure', methods=['GET', 'POST'])
def configure():
    exam_id = request.args.get('exam_id')
    token = request.args.get('jwt')
    integration_info = get_integration_info(exam_id)
    try:
        decoded = jwt.decode(token, integration_info['secret'], algorithms=['HS256'])
    except jwt.exceptions.InvalidTokenError:
        abort(403)
    form = ConfigureForm(**integration_info)
    if form.validate_on_submit():
        integration_info['sftp_host'] = form.sftp_host.data
        integration_info['sftp_port'] = form.sftp_port.data
        integration_info['sftp_user'] = form.sftp_user.data
        integration_info['sftp_password'] = form.sftp_password.data
        integration_info['sftp_path'] = form.sftp_path.data
        redis_store.set(exam_id, dumps(integration_info))
        return redirect(url_for('complete'))
    return render_template('configure.html', exam_id=exam_id, token=token, form=form)


@app.route('/complete')
def complete():
    return render_template('complete.html')
