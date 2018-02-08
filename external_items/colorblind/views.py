from flask import Blueprint, url_for, render_template, request, redirect, jsonify, abort, current_app
import requests
from helpers import get_integration_info, redis_store


colorblind_bp = Blueprint('colorblind', __name__, template_folder='templates', static_folder='static', url_prefix='/colorblind')


@colorblind_bp.route('/url')
def get_url():
    external_token = request.args.get('external_token')
    response_id = request.args.get('response_id')
    if external_token and response_id:
        # store the external token in redis and remove it from the url we send back
        redis_store.setex(response_id, 7200, external_token)
    args = {key: value for key, value in request.args.items() if key != 'external_token'}
    return url_for('colorblind.colorblind', _external=True, **args)


@colorblind_bp.route('/', methods=['GET', 'POST'])
def colorblind():
    if request.method == 'POST':
        response_id = request.args.get('response_id')
        if response_id:
            exam_id = request.args.get('exam_id')
            # check first if we have an external token in redis
            external_token = redis_store.get(response_id)
            url = current_app.config['SEI_URL_BASE'] + '/api/set_response/' + response_id
            json = {
                'value': request.form['submit']
            }
            if external_token:
                url += '?external_token=' + external_token
                r = requests.post(url, json=json)
            elif exam_id:
                try:
                    integration_info = get_integration_info(exam_id)
                except ValueError:
                    abort(400)
                token = integration_info['token']
                headers = {
                    'Authorization': 'Bearer {0}'.format(token)
                }
                r = requests.post(url, json=json, headers=headers)
            else:
                r = None
            if r and r.status_code not in {200, 201}:
                abort(400)
        return redirect(url_for('colorblind.thank_you'))
    return render_template('colorblind.html', query_params=request.args)


@colorblind_bp.route('/thank_you')
def thank_you():
    return render_template('thank_you.html')
