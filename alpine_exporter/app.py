from datetime import datetime, timedelta
from json import loads, dumps

import jwt
import requests
from flask import Flask, render_template, request, abort, Response, redirect, url_for
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFProtect
from requests.auth import HTTPBasicAuth
from werkzeug.contrib.fixers import ProxyFix
from wtforms import StringField, IntegerField
from wtforms.validators import Optional, ValidationError

from helpers import redis_store, get_integration_info, Exporter

# app setup
app = Flask(__name__)
app.config.from_pyfile('config.py')
if app.config['PREFERRED_URL_SCHEME'] == 'https':
    app.wsgi_app = ProxyFix(app.wsgi_app)

app.url_map.strict_slashes = False
csrf = CSRFProtect(app)


# forms
class ConfigureForm(FlaskForm):
    secret = StringField('Secret Key')
    sftp_host = StringField('SFTP Host')
    sftp_port = IntegerField('SFTP Port', validators=[Optional()])
    sftp_user = StringField('SFTP User')
    sftp_password = StringField('SFTP Password')
    sftp_path = StringField('SFTP Path')
    last_timestamp = StringField('Last Pulled At (Changing this value might cause deliveries to be duplicated or missed)')

    def validate_sftp_path(self, field):
        if field.data and not field.data.endswith('/'):
            raise ValidationError('Must end with /')


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

    type = request.args.get('type')
    start = request.args.get('start')

    end = request.args.get('end')
    if end:
        end_obj = datetime.strptime(end, '%Y-%m-%d')
        end_obj += timedelta(hours=24)
        end = end_obj.strftime('%Y-%m-%d')

    exporter = Exporter(exam_id, integration_info, type, start, end)

    filename = exporter.filename
    response = Response(exporter.generate_csv(), mimetype='text/csv')
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
        integration_info['sftp_path'] = form.sftp_path.data
        integration_info['last_timestamp'] = form.last_timestamp.data
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
