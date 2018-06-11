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
    redis_store.set(data['exam_id'], dumps(data))
    return render_template('sei_redirect.html')


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

    # get full delivery object from SEI
    delivery_id = body['delivery_id']
    delivery_url = '{0}/api/exams/{1}/deliveries/{2}?include=exam'.format(app.config['SEI_URL_BASE'], exam_id, delivery_id)
    delivery_headers = {'Authorization': 'Bearer {0}'.format(integration_info['token'])}
    delivery_response = requests.get(delivery_url, headers=delivery_headers)
    delivery_json = delivery_response.json()

    # todo: make the request configurable in the UI and store in db instead of these conditionals

    trainingrocket_url_base = app.config.get('TRAININGROCKET_URL_BASE')
    if trainingrocket_url_base:
        headers = {
            'TrainingRocket-Authorization': app.config['TRAININGROCKET_API_TOKEN'],
            'Accept': 'application/json'
        }
        enrollment_id = delivery_json['examinee']['info'].get('Enrollment ID')
        # url = trainingrocket_url_base + '/api/rest/v2/manage/exam_session'
        # try:
        #     pct_score = delivery_json['points_earned'] / delivery_json['points_available']
        # except (TypeError, ZeroDivisionError):
        #     pct_score = 0
        # payload = {
        #     'enrolmentId': enrollment_id,
        #     'score': pct_score,
        #     'maxScore': delivery_json['points_available'] or 100,
        #     'rawScore': delivery_json['points_earned'] or 0
        # }
        # requests.post(url, json=payload, headers=headers)
        status_url = trainingrocket_url_base + '/api/rest/v2/manage/enrolment/' + enrollment_id
        if delivery_json.get('passed'):
            status = 'PASSED'
        else:
            status = 'FAILED'
        status_payload = {
            'status': status
        }
        requests.post(status_url, json=status_payload, headers=headers)

    slack_webhook_url = app.config.get('SLACK_WEBHOOK_URL')
    if slack_webhook_url:
        channel = app.config.get('SLACK_CHANNEL', '#general')
        examinee_attachment = {
            'pretext': 'Someone has completed a delivery in the {0} exam'.format(delivery_json['exam']['name']),
            'title': 'Examinee Info',
            'text': '```{0}```'.format(dumps(delivery_json['examinee']['info'], sort_keys=True, indent=4, separators=(',', ': '))),
            'mrkdwn_in': [
                'text'
            ]
        }
        delivery_info = {
            'score': delivery_json['score'],
            'score_scale': delivery_json['score_scale'],
            'passed': delivery_json['passed'],
            'points_earned': delivery_json['points_earned'],
            'points_available': delivery_json['points_available']
        }
        delivery_attachment = {
            'title': 'Delivery Info',
            'text': '```{0}```'.format(dumps(delivery_info, sort_keys=True, indent=4, separators=(',', ': '))),
            'mrkdwn_in': [
                'text'
            ]
        }
        slack_payload = {
            'username': 'SEI Result Connector',
            'icon_emoji': ':owl:',
            'channel': channel,
            'attachments': [examinee_attachment, delivery_attachment]
        }
        requests.post(slack_webhook_url, json=slack_payload)
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
