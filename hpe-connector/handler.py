import json
import os

import requests


CREDENTIALS = {
    'b3643010-ebaa-4f62-b968-345c58f43d2d': {
        'token': 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJTRUkiLCJzdWIiOiJkZDdhYTc3Yi03Mzg0LTRhOWQtYjE2Yy04ODk0OWFiOTM0YmEiLCJpYXQiOjE1Njg5MzUxMzAsInR5cGUiOiJpbnRlZ3JhdGlvbiJ9.JhnsHytE3yG_RBS07lTQDJ9boW_xx5tQXM6tOlUijJg',
        'secret': 'a5bc6d4d0acef38b6bd27e9bad031b63'
    }
}


def handle_sei_event(event, context):
    body = event['body']
    exam_id = body['exam_id']
    if exam_id not in CREDENTIALS:
        raise ValueError('No exam with that ID')

    delivery_id = body['delivery_id']
    delivery_json = get_delivery_json(exam_id, delivery_id)

    psi_response = send_to_psi(delivery_json)
    saba_response = send_to_saba(delivery_json)

    send_to_slack(delivery_json, psi_response, saba_response)

    response = {
        'statusCode': 200,
        'body': '{}'
    }

    return response


def get_delivery_json(exam_id, delivery_id):
    delivery_url = '{0}/api/exams/{1}/deliveries/{2}?include=exam'.format(os.environ['SEI_URL_BASE'], exam_id,
                                                                          delivery_id)
    delivery_headers = {'Authorization': 'Bearer {0}'.format(CREDENTIALS[exam_id]['token'])}
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


def send_to_slack(delivery_json, psi_response, saba_response):
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

        slack_payload = {
            'username': 'HPE Connector',
            'icon_emoji': ':owl:',
            'channel': channel,
            'attachments': [examinee_attachment, delivery_attachment, psi_attachment, saba_attachment]
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
