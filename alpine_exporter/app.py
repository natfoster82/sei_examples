from json import loads, dumps

import requests
import jwt
from flask import Flask, render_template, request, abort, jsonify
from redis import StrictRedis
from requests.auth import HTTPBasicAuth
from werkzeug.contrib.fixers import ProxyFix


# app setup
app = Flask(__name__)
app.config.from_pyfile('config.py')
if app.config['PREFERRED_URL_SCHEME'] == 'https':
    app.wsgi_app = ProxyFix(app.wsgi_app)

app.url_map.strict_slashes = False


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


@app.route('/export', methods=['POST'])
def export():
    data = request.get_json()
    exam_id = data['exam_id']
    token = request.headers['Authorization'].split()[1]
    integration_info = get_integration_info(exam_id)
    try:
        decoded = jwt.decode(token, integration_info['secret'], algorithms=['HS256'])
    except jwt.exceptions.InvalidTokenError:
        abort(403)

    return jsonify()


@app.route('/complete')
def complete():
    return render_template('complete.html')
