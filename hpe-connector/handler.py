import json
import os

import boto3
import jwt
import requests


s3 = boto3.client('s3')


def authorize_sei_event(auth_header, secret):
    token = auth_header.split()[1]
    try:
        jwt.decode(token, secret, algorithms=['HS256'])
        return True
    except jwt.exceptions.InvalidTokenError:
        return False


def handle_sei_event(event, context):
    body = event['body']
    exam_id = body['exam_id']
    headers = event['headers']
    credentials = get_credentials_dict()
    exam_credentials = credentials[exam_id]
    secret = exam_credentials['secret']

    if not authorize_sei_event(headers['Authorization'], secret):
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
    saba_response = send_to_saba(delivery_json)
    ip_response = check_ip()

    send_to_slack(delivery_json, psi_response, saba_response, ip_response)

    response = {
        'statusCode': 200,
        'body': '{}'
    }

    return response


def get_credentials_dict():
    data = s3.get_object(Bucket='caveon-private', Key='hpe_creds.json')
    return json.loads(data['Body'].read())


def get_delivery_json(exam_id, delivery_id, token):
    delivery_url = '{0}/api/exams/{1}/deliveries/{2}?include=exam'.format(os.environ['SEI_URL_BASE'], exam_id,
                                                                          delivery_id)
    delivery_headers = {'Authorization': 'Bearer {0}'.format(token)}
    delivery_response = requests.get(delivery_url, headers=delivery_headers)
    return delivery_response.json()


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
    r = requests.put(url, json=payload)
    return {'Status Code': r.status_code}


def send_to_saba(delivery_json):
    return {'Status Code': None}


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
