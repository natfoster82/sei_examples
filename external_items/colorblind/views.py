from flask import Blueprint, url_for, render_template, request, redirect, jsonify, abort, current_app
import requests
from helpers import get_integration_info


colorblind_bp = Blueprint('colorblind', __name__, template_folder='templates', static_folder='static', url_prefix='/colorblind')


@colorblind_bp.route('/url')
def get_url(route):
    return url_for(route, _external=True, **request.args)


@colorblind_bp.route('/', methods=['GET', 'POST'])
def colorblind():
    if request.method == 'POST':
        response_id = request.args.get('response_id')
        if response_id:
            exam_id = request.args.get('exam_id')
            external_token = request.args.get('external_token')
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
