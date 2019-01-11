from json import loads, dumps

import jwt
import requests
from flask import Flask, render_template, request, abort, Response, redirect, url_for
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFProtect
from redis import StrictRedis
from requests.auth import HTTPBasicAuth
from werkzeug.contrib.fixers import ProxyFix
from wtforms import StringField, IntegerField


# app setup
app = Flask(__name__)
app.config.from_pyfile('config.py')
if app.config['PREFERRED_URL_SCHEME'] == 'https':
    app.wsgi_app = ProxyFix(app.wsgi_app)

app.url_map.strict_slashes = False
csrf = CSRFProtect(app)

# some helpers
redis_store = StrictRedis.from_url(app.config['REDIS_URL'], db=app.config['REDIS_DB'], decode_responses=True)
rq_store = StrictRedis.from_url(app.config['REDIS_URL'], db=app.config['REDIS_DB'])


class ConfigureForm(FlaskForm):
    secret = StringField('Secret Key')
    sftp_host = StringField('SFTP Host')
    sftp_port = IntegerField('SFTP Port')
    sftp_user = StringField('SFTP User')
    sftp_password = StringField('SFTP Password')


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


def get_client_id(examinee_info, secret):
    try:
        client_id = examinee_info['id']
    except KeyError:
        try:
            client_jwt = examinee_info['jwt']
            try:
                decoded_jwt = jwt.decode(client_jwt, secret, algorithms=['HS256'])
                client_id = decoded_jwt['id']
            except jwt.exceptions.InvalidTokenError:
                client_id = ''
        except KeyError:
            client_id = ''
    return client_id


def make_row(delivery, exam_title, secret):
    client_id = get_client_id(delivery['examinee']['info'], secret)
    exam_grade = 'p' if delivery['passed'] else 'f'
    score = str(delivery['score'])
    try:
        cutscore = str(delivery['cutscore']['score'])
    except KeyError:
        cutscore = ''

    items_correct = delivery['points_earned']
    items_total = delivery['points_available']
    items_incorrect = items_total - items_correct

    values = [
        delivery['examinee_id'],
        client_id,
        delivery['exam_id'],
        delivery['examinee_id'],
        delivery['modified_at'],
        str(delivery['used_seconds']),
        exam_grade,
        score,
        cutscore,
        exam_title,
        delivery['form_id'],
        str(items_correct),
        str(items_incorrect),
        '0',
        'OK',
        score
    ]
    return ', '.join(values) + '\r\n'


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
    existing_data = redis_store.get(exam_id)
    if existing_data:
        existing_data = loads(existing_data)
        existing_data.update(data)
        data = existing_data
    redis_store.set(exam_id, dumps(data))
    return render_template('complete.html')


@app.route('/export_widget')
def export_widget():
    exam_id = request.args.get('exam_id')
    token = request.args.get('jwt')
    integration_info = get_integration_info(exam_id)
    try:
        decoded = jwt.decode(token, integration_info['secret'], algorithms=['HS256'])
    except jwt.exceptions.InvalidTokenError:
        abort(403)
    return render_template('export_widget.html', exam_id=exam_id, token=token)


@app.route('/export')
def export():
    exam_id = request.args.get('exam_id')
    token = request.args.get('jwt')
    integration_info = get_integration_info(exam_id)
    try:
        decoded = jwt.decode(token, integration_info['secret'], algorithms=['HS256'])
    except jwt.exceptions.InvalidTokenError:
        abort(403)

    columns = [
        'cand_id',
        'cand_client_id',
        'exam_id',
        'exam_cand_id',
        'exam_date_time',
        'exam_time_spent',
        'exam_grade',
        'exam_score',
        'exam_passing_score',
        'exam_title',
        'exam_form',
        'exam_items_correct',
        'exam_items_incorrect',
        'exam_items_skipped',
        'exam_result_status',
        'exam_score_scaled'
    ]

    headers = {'Authorization': 'Bearer {0}'.format(integration_info['token'])}
    exam_url = '{0}/api/exams/{1}?only=name'.format(app.config['SEI_URL_BASE'], exam_id)
    exam_resp = requests.get(exam_url, headers=headers)
    exam_title = exam_resp.json()['name']
    exam_title_escaped = '"{}"'.format(exam_title)

    secret = integration_info.get('secret', 'invalid secret')

    def generate():
        page = 0
        has_next = True

        yield '\t'.join((x for x in columns)) + '\r\n'

        while has_next:
            page += 1
            url = '{0}/api/exams/{1}/deliveries?page={2}&status=complete'.format(app.config['SEI_URL_BASE'], exam_id, str(page))
            r = requests.get(url, headers=headers)
            data = r.json()
            has_next = data['has_next']
            for delivery in data['results']:
                try:
                    row = make_row(delivery, exam_title_escaped, secret)
                    yield row
                except Exception as e:
                    print(e)

    filename = 'export.csv'
    response = Response(generate(), mimetype='text/csv')
    response.headers['Content-Disposition'] = 'attachment; filename="{0}"'.format(filename)
    return response


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
        integration_info['secret'] = form.secret.data
        integration_info['sftp_host'] = form.sftp_host.data
        integration_info['sftp_port'] = form.sftp_port.data
        integration_info['sftp_user'] = form.sftp_user.data
        integration_info['sftp_password'] = form.sftp_password.data
        redis_store.set(exam_id, dumps(integration_info))
        if integration_info['sftp_host']:
            redis_store.sadd('cron_ids', exam_id)
        else:
            redis_store.srem('cron_ids', exam_id)
        return redirect(url_for('complete'))
    return render_template('configure.html', exam_id=exam_id, token=token, form=form)


@app.route('/complete')
def complete():
    return render_template('complete.html')
