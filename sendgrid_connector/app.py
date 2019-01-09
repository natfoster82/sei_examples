from datetime import datetime, timedelta
from json import loads, dumps
from multiprocessing.dummy import Pool as ThreadPool

import requests
import jwt
from flask import Flask, render_template, request, abort, jsonify, redirect, url_for
from flask_wtf import FlaskForm
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

# some helpers
redis_store = StrictRedis.from_url(app.config['REDIS_URL'], db=app.config['REDIS_DB'], decode_responses=True)
pool = ThreadPool(4)


def make_request(request_dict):
    response = requests.get(request_dict['url'], headers=request_dict['headers'])
    return response.json()


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


def build_template_data(delivery, to_dict):
    try:
        score_percent = delivery['points_earned'] / delivery['points_available']
    except Exception:
        score_percent = 0.0
    score_report_url = app.config['SEI_URL_BASE'] + '/score/' + delivery['score_token']
    data = {
        'name': to_dict['name'],
        'email': to_dict['email'],
        'examinee_info': delivery['examinee']['info'],
        'exam_name': delivery['exam']['name'],
        'score': delivery['score'],
        'score_scale': delivery['score_scale'],
        'points_earned': delivery['points_earned'],
        'points_available': delivery['points_available'],
        'score_percent': score_percent,
        'passed': delivery['passed'],
        'cutscore': delivery['cutscore'],
        'content_area_breakdown': delivery['content_area_breakdown'],
        'status': delivery['status'],
        'type': delivery['type'],
        'duration': delivery['used_seconds'],
        'score_report_url': score_report_url
    }
    return data


def build_to(name_map, email_map, examinee_info):
    name = str(name_map)
    for key in examinee_info:
        key_code = '[{0}]'.format(key)
        name = name.replace(key_code, examinee_info[key])
    email = str(email_map)
    for key in examinee_info:
        key_code = '[{0}]'.format(key)
        email = email.replace(key_code, examinee_info[key])
    return {'name': name, 'email': email}


class ApiKeyForm(FlaskForm):
    # TODO: build api key validator
    api_key = StringField('API Key')


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
    return redirect(url_for('switch', jwt=token, exam_id=exam_id))


@app.route('/events', methods=['POST'])
def events():
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
    # TODO: only do this for delivery type events
    delivery_id = body['delivery_id']
    delivery_url = '{0}/api/exams/{1}/deliveries/{2}?include=exam,content_area_breakdown,score_token'.format(app.config['SEI_URL_BASE'], exam_id, delivery_id)
    delivery_headers = {'Authorization': 'Bearer {0}'.format(integration_info['token'])}
    delivery_response = requests.get(delivery_url, headers=delivery_headers)
    delivery_json = delivery_response.json()
    examinee_info = delivery_json['examinee']['info']
    api_key = integration_info.get('api_key')
    if api_key:
        event = body['event']
        configs = integration_info.get('configs', [])
        sg_url = 'https://api.sendgrid.com/v3/mail/send'
        sg_headers = {'Authorization': 'Bearer {0}'.format(api_key)}
        for config in configs:
            if config['event'] == event:
                to_dict = build_to(config['name'], config['email'], examinee_info)
                from_dict = {'name': config.get('sender_name'), 'email': config.get('sender_email')}
                sg_payload = {
                    'from': from_dict,
                    'template_id': config['template_id'],
                    'personalizations': [{
                        'to': [to_dict],
                        'dynamic_template_data': build_template_data(delivery_json, to_dict)
                    }]
                }
                requests.post(sg_url, json=sg_payload, headers=sg_headers)
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


@app.route('/switch')
def switch():
    exam_id = request.args.get('exam_id')
    token = request.args.get('jwt')
    integration_info = get_integration_info(exam_id)
    try:
        decoded = jwt.decode(token, integration_info['secret'], algorithms=['HS256'])
    except jwt.exceptions.InvalidTokenError:
        abort(403)

    if integration_info.get('api_key'):
        return redirect(url_for('configure', **request.args))
    return redirect(url_for('api_key', **request.args))


@app.route('/api_key', methods=['GET', 'POST'])
def api_key():
    exam_id = request.args.get('exam_id')
    token = request.args.get('jwt')
    integration_info = get_integration_info(exam_id)
    try:
        decoded = jwt.decode(token, integration_info['secret'], algorithms=['HS256'])
    except jwt.exceptions.InvalidTokenError:
        abort(403)
    form = ApiKeyForm(api_key=integration_info.get('api_key'))
    if form.validate_on_submit():
        integration_info['api_key'] = form.api_key.data
        redis_store.set(exam_id, dumps(integration_info))
        return redirect(url_for('configure', exam_id=exam_id, jwt=token))
    bad_key = request.args.get('bad_key') == 'true'
    return render_template('api_key.html', form=form, bad_key=bad_key)


@app.route('/configure')
def configure():
    exam_id = request.args.get('exam_id')
    token = request.args.get('jwt')
    integration_info = get_integration_info(exam_id)
    try:
        decoded = jwt.decode(token, integration_info['secret'], algorithms=['HS256'])
    except jwt.exceptions.InvalidTokenError:
        abort(403)

    request_dicts = []

    url = '{0}/api/exams/{1}?only=examinee_schema'.format(app.config['SEI_URL_BASE'], exam_id)
    headers = {'Authorization': 'Bearer {0}'.format(integration_info['token'])}
    request_dicts.append({'url': url, 'headers': headers})

    sg_base = 'https://api.sendgrid.com/v3'
    sg_headers = {'Authorization': 'Bearer {0}'.format(integration_info['api_key'])}

    templates_url = sg_base + '/templates?generations=dynamic'
    request_dicts.append({'url': templates_url, 'headers': sg_headers})

    senders_url = sg_base + '/senders'
    request_dicts.append({'url': senders_url, 'headers': sg_headers})

    exam_json, templates_json, senders_json = pool.map(make_request, request_dicts)
    schema = exam_json['examinee_schema']
    try:
        templates = templates_json['templates']
    except KeyError:
        return redirect(url_for('api_key', exam_id=exam_id, jwt=token, bad_key='true'))
    senders = senders_json

    configs = integration_info.get('configs', [])

    return render_template('configure.html', exam_id=exam_id, token=token, schema=schema,
                           templates=templates, senders=senders, configs=configs)


@app.route('/configure', methods=['POST'])
def post_configuration():
    data = request.get_json()
    exam_id = request.args.get('exam_id')
    token = request.args.get('jwt')
    integration_info = get_integration_info(exam_id)
    try:
        decoded = jwt.decode(token, integration_info['secret'], algorithms=['HS256'])
    except jwt.exceptions.InvalidTokenError:
        return jsonify(), 403
    integration_info['configs'] = data['configs']
    redis_store.set(exam_id, dumps(integration_info))
    return jsonify()


@app.route('/complete')
def complete():
    return render_template('complete.html')
