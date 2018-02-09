from json import dumps

import requests
from flask import Flask, render_template, request, abort
from requests.auth import HTTPBasicAuth
from werkzeug.contrib.fixers import ProxyFix

from colorblind.views import colorblind_bp
from connect4.views import connect4_bp
from helpers import redis_store

# app setup
app = Flask(__name__)
app.config.from_pyfile('config.py')
if app.config['PREFERRED_URL_SCHEME'] == 'https':
    app.wsgi_app = ProxyFix(app.wsgi_app)

app.url_map.strict_slashes = False

app.register_blueprint(colorblind_bp)
app.register_blueprint(connect4_bp)


# base views
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
