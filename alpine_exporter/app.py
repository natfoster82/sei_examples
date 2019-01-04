from json import loads, dumps

import requests
import jwt
from flask import Flask, render_template, request, abort, jsonify, Response
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


def make_row(delivery, exam_title):
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
        'get from jwt',
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
                    row = make_row(delivery, exam_title_escaped)
                    yield row
                except Exception as e:
                    print(e)

    filename = 'export.csv'
    response = Response(generate(), mimetype='text/csv')
    response.headers['Content-Disposition'] = 'attachment; filename="{0}"'.format(filename)
    return response


@app.route('/complete')
def complete():
    return render_template('complete.html')
