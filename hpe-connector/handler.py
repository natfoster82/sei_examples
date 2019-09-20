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

    send_to_psi(delivery_json)
    send_to_saba(delivery_json)

    response = {
        'statusCode': 200,
        'body': json.dumps(delivery_json)
    }

    return response


def get_delivery_json(exam_id, delivery_id):
    delivery_url = '{0}/api/exams/{1}/deliveries/{2}?include=exam'.format(os.environ['SEI_URL_BASE'], exam_id,
                                                                          delivery_id)
    delivery_headers = {'Authorization': 'Bearer {0}'.format(CREDENTIALS[exam_id]['token'])}
    delivery_response = requests.get(delivery_url, headers=delivery_headers)
    return delivery_response.json()


def send_to_psi(delivery_json):
    booking_code = 'CAFLH8DY'
    payload = {
      "result": "PASS",
      "score": "90"
    }
    url = '{}/assessmentResultService/1.0.0/bookings/{}/results'.format(os.environ['PSI_URL_BASE'], booking_code)
    r = requests.put(url, json=payload)
    print(url)
    print(r.status_code)
    print(r.text)


def send_to_saba(delivery_json):
    pass
