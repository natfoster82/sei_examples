import json
import os
from datetime import datetime

import boto3
import jwt
import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape
from requests.auth import HTTPBasicAuth


s3 = boto3.client('s3')
env = Environment(
    loader=FileSystemLoader('templates'),
    autoescape=select_autoescape(['html', 'xml'])
)


def handle_sei_event(event, context):
    body = json.loads(event['body'])
    exam_id = body['exam_id']
    headers = event['headers']
    credentials = get_credentials_dict()
    exam_credentials = credentials[exam_id]
    secret = exam_credentials['secret']
    auth_header = headers['Authorization']
    token = auth_header.split()[1]

    if not authorize_sei_event(token, secret):
        response = {
            'statusCode': 403,
            'body': '{}'
        }
        return response

    token = exam_credentials['token']

    delivery_id = body['delivery_id']
    delivery_json = get_delivery_json(exam_id, delivery_id, token)

    # TODO: run these in parallel
    psi_response = send_to_psi(delivery_json)

    saba_response = None
    if delivery_json['passed']:
        saba_response = send_to_saba(delivery_json)

    ip_response = check_ip()

    send_to_slack(delivery_json, psi_response, saba_response, ip_response)

    response = {
        'statusCode': 200,
        'body': '{}'
    }

    return response


def handle_delivery_widget(event, context):
    args = event['queryStringParameters']
    exam_id = args['exam_id']
    delivery_id = args['delivery_id']
    token = args['jwt']
    stage = os.environ['STAGE']
    credentials = get_credentials_dict()
    exam_credentials = credentials[exam_id]
    secret = exam_credentials['secret']

    if not authorize_sei_event(token, secret):
        response = {
            'statusCode': 403,
            'body': '{}'
        }
        return response

    template = env.get_template('delivery_widget.html')
    content = template.render(exam_id=exam_id, delivery_id=delivery_id, token=token, stage=stage)

    response = {
        'statusCode': 200,
        'body': content,
        'headers': {
            'Content-Type': 'text/html',
        }
    }
    return response


def authorize_sei_event(token, secret):
    try:
        jwt.decode(token, secret, algorithms=['HS256'])
        return True
    except jwt.exceptions.InvalidTokenError:
        return False


def get_credentials_dict():
    key = 'hpe/{}/creds.json'.format(os.environ['STAGE'])
    data = s3.get_object(Bucket='caveon-private', Key=key)
    return json.loads(data['Body'].read())


def get_delivery_json(exam_id, delivery_id, token):
    delivery_url = '{0}/api/exams/{1}/deliveries/{2}?include=exam'.format(os.environ['SEI_URL_BASE'], exam_id,
                                                                          delivery_id)
    delivery_headers = {'Authorization': 'Bearer {0}'.format(token)}
    delivery_response = requests.get(delivery_url, headers=delivery_headers)
    return delivery_response.json()


def get_psi_token():
    url = '{}/token'.format(os.environ['PSI_URL_BASE'])
    data = {
        'grant_type': 'password',
        'username': os.environ.get('PSI_USERNAME', 'caveon'),
        'password': os.environ['PSI_PASSWORD']
    }
    response = requests.post(url=url, data=data, auth=HTTPBasicAuth(username=os.environ['PSI_CONSUMER_KEY'], password=os.environ['PSI_CONSUMER_SECRET']))
    return response.json()['access_token']


def send_to_psi(delivery_json):
    examinee_info = delivery_json['examinee']['info']
    booking_code = examinee_info.get('bookingcode')
    score = delivery_json['score']
    result = 'PASS' if delivery_json['passed'] else 'FAIL'
    payload = {
      'result': result,
      'score': score
    }
    url = '{}/assessmentResultService/1.0.0/bookings/{}/results'.format(os.environ['PSI_URL_BASE'], booking_code)
    psi_token = get_psi_token()
    headers = {
        'Authorization': 'Bearer {}'.format(psi_token)
    }
    r = requests.put(url, json=payload, headers=headers)
    return {'Status Code': r.status_code}


def get_saba_cert():
    url = '{}/v1/login'.format(os.environ['SABA_URL_BASE'])
    headers = {
        'user': os.environ['SABA_USER'],
        'password': os.environ['SABA_PASSWORD'],
        'site': os.environ['SABA_SITE']
    }
    r = requests.get(url, headers=headers)
    return r.json()['certificate']


def get_saba_person_id(certificate, unique_id):
    if not unique_id:
        unique_id = '994633d0271065fd25248485dd83c363'
    url = '{}/v1/people/username={}'.format(os.environ['SABA_URL_BASE'], unique_id)
    headers = {
        'SabaCertificate': certificate
    }
    r = requests.get(url, headers=headers)
    return r.json().get('id')


def get_saba_course_id(readable_course_id=None):
    # TODO: get the readable_course_id from the exam title and make a request here:
    # https://hpe-itg-api.sabacloud.com/v1/course/course_no=HPE1-H01
    # then return the r.json()['id']
    # hardcoded for now
    return 'cours000000001189168'


def send_to_saba(delivery_json):
    examinee_info = delivery_json['examinee']['info']
    unique_id = examinee_info.get('uniqueID')
    cert = get_saba_cert()
    course_id = get_saba_course_id()
    person_id = get_saba_person_id(cert, unique_id)

    if person_id:
        url = '{}/v1/transcript'.format(os.environ['SABA_URL_BASE'])
        headers = {
            'SabaCertificate': cert
        }
        payload = build_saba_payload(course_id, person_id, delivery_json['score'])

        r = requests.post(url, headers=headers, json=payload)
        status_code = r.status_code
    else:
        status_code = None

    return {'Status Code': status_code}


def build_saba_payload(course_id, person_id, score):
    now = datetime.utcnow()

    date = now.strftime('%Y-%m-%d')
    time = now.strftime('%H:%M')
    delivered_by = 'emplo000000005308513'
    delivery_type = 'Exam/Test (On Demand)'
    payload = {
        '@type': 'com.saba.offering.adhoclearning.AdHocLearningTranscriptDetail',
        'offeringStartDate': {
            '@type': 'date',
            'time': date
        },
        'startTime': time,
        'deliveredBy': delivered_by, # can be added in a config file or hard coded, set to PEARSON today. Need to create one for Caveon. Value will change in PROD.
        'deliveryType': delivery_type, # can be added in a config file or hard coded, mapped to Exam/Test (On Demand)
        'courseId': course_id, # this is the ID from the course lookup call
        'learners': [
            'java.util.ArrayList',
            [
                {
                    '@type': 'com.saba.offering.adhoclearning.LearnerInfo',
                    'learnerId': person_id,  # this is the ID from the people lookup call
                    'grade': 'Pass',
                    'score': [
                        'java.math.BigDecimal',
                        score
                    ],
                    'completedOnDate': {
                        '@type': 'date',
                        'time': date
                    }
                }
            ]
        ],
        'customValues': [
            'list',
            [
                {
                    '@type': 'CustomAttributeValueDetail',
                    'name': 'custom2',
                    'datatype': {
                        '@type': 'CustomAttributeDatatype',
                        'value': '18'
                    },
                    'value': None  # Test Location
                },
                {
                    '@type': 'CustomAttributeValueDetail',
                    'name': 'custom3',
                    'datatype': {
                        '@type': 'CustomAttributeDatatype',
                        'value': '18'
                    },
                    'value': None  # Exam Result First Name
                },
                {
                    '@type': 'CustomAttributeValueDetail',
                    'name': 'custom4',
                    'datatype': {
                        '@type': 'CustomAttributeDatatype',
                        'value': '18'
                    },
                    'value': None  # Exam Result Last Name
                },
                {
                    '@type': 'CustomAttributeValueDetail',
                    'name': 'custom5',
                    'datatype': {
                        '@type': 'CustomAttributeDatatype',
                        'value': '18'
                    },
                    'value': None  # Exam Result Vendor Exam ID
                },
                {
                    '@type': 'CustomAttributeValueDetail',
                    'name': 'custom6',
                    'datatype': {
                        '@type': 'CustomAttributeDatatype',
                        'value': '18'
                    },
                    'value': None  # Exam Result Test Location
                }
            ]
        ]
    }
    return payload


def check_ip():
    r = requests.get('https://api.ipify.org?format=json')
    return r.json()


def send_to_slack(delivery_json, psi_response, saba_response, ip_response):
    webhook_url = os.environ.get('SLACK_WEBHOOK_URL')
    if webhook_url:
        channel = os.environ.get('SLACK_CHANNEL', '#dev')
        examinee_attachment = {
            'pretext': 'Someone has completed a delivery in the {0} exam'.format(delivery_json['exam']['name']),
            'title': 'Examinee Info',
            'text': '```{0}```'.format(
                json.dumps(delivery_json['examinee']['info'], sort_keys=True, indent=4, separators=(',', ': '))),
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

        delivery_attachment = format_attachment('Delivery Info', delivery_info)
        psi_attachment = format_attachment('PSI Status', psi_response)
        saba_attachment = format_attachment('SABA Status', saba_response)
        ip_attachment = format_attachment('Connector IP', ip_response)

        slack_payload = {
            'username': 'HPE Connector',
            'icon_emoji': ':owl:',
            'channel': channel,
            'attachments': [examinee_attachment, delivery_attachment, psi_attachment, saba_attachment, ip_attachment]
        }
        requests.post(webhook_url, json=slack_payload)


def format_attachment(title, data):
    attachment = {
        'title': title,
        'text': '```{0}```'.format(json.dumps(data, sort_keys=True, indent=4, separators=(',', ': '))),
        'mrkdwn_in': [
            'text'
        ]
    }
    return attachment



