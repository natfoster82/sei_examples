from datetime import datetime, timedelta
from json import loads, dumps

import requests
import jwt
from flask import Flask, render_template, request, abort, jsonify, redirect, url_for
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFProtect
from jinja2.sandbox import SandboxedEnvironment
from redis import StrictRedis
from requests.auth import HTTPBasicAuth
from werkzeug.contrib.fixers import ProxyFix
from wtforms import StringField


# app setup
app = Flask(__name__)
app.config.from_pyfile('config.py')
if app.config['PREFERRED_URL_SCHEME'] == 'https':
    app.wsgi_app = ProxyFix(app.wsgi_app)

app.url_map.strict_slashes = False

csrf = CSRFProtect(app)


# some helpers
redis_store = StrictRedis.from_url(app.config['REDIS_URL'], db=app.config['REDIS_DB'], decode_responses=True)


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
    api_key = StringField('API Key')
    group_id = StringField('Group ID')
    name_map = StringField('Name Map')
    email_map = StringField('Email Map')


sandbox = SandboxedEnvironment()


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
@csrf.exempt
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

    # get full delivery object from SEI
    delivery_id = body['delivery_id']
    delivery_url = '{0}/api/exams/{1}/deliveries/{2}?include=exam'.format(app.config['SEI_URL_BASE'], exam_id, delivery_id)
    delivery_headers = {'Authorization': 'Bearer {0}'.format(integration_info['token'])}
    delivery_response = requests.get(delivery_url, headers=delivery_headers)
    delivery_json = delivery_response.json()
    api_key = integration_info.get('api_key')
    group_id = integration_info.get('group_id')
    if delivery_json['passed'] and api_key and group_id:
        url = 'https://api.accredible.com/v1/credentials'
        name = None
        email = None
        examinee_info = delivery_json['examinee']['info']

        name_map = integration_info.get('name_map')
        if name_map:
            name_template = sandbox.from_string(name_map)
            name = name_template.render(**examinee_info)
        else:
            for key in examinee_info:
                if 'name' in key.lower():
                    name = examinee_info[key]
                    break

        email_map = integration_info.get('email_map')
        if email_map:
            email_template = sandbox.from_string(email_map)
            email = email_template.render(**examinee_info)
        else:
            for key in examinee_info:
                if 'email' in key.lower():
                    email = examinee_info[key]
                    break

        if not name or not email:
            return jsonify(), 400

        payload = {
            'group_id': group_id,
            'name': name,
            'email': email
        }
        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Token token={0}'.format(api_key)
        }
        requests.post(url, json=payload, headers=headers)
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
    return render_template('delivery_widget.html', exam_id=exam_id, delivery_id=delivery_id, token=token)


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
        integration_info['slack_webhook_url'] = form.slack_webhook_url.data
        integration_info['slack_channel'] = form.slack_channel.data
        redis_store.set(exam_id, dumps(integration_info))
        return redirect(url_for('complete'))
    return render_template('configure.html', exam_id=exam_id, token=token, form=form)


@app.route('/complete')
def complete():
    return render_template('complete.html')
