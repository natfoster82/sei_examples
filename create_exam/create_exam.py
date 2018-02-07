import requests
from requests.auth import HTTPBasicAuth
from pprint import pprint


sei_id = input('What is your app\'s ID? ')
sei_secret = input('What is your app\'s secret? ')
exam_name = input('What do you want to call your exam? ')

url = 'https://sei.caveon.com/api/exams'

payload = {
    'name': exam_name
}

print('Creating exam')
post_response = requests.post(url,
                              json=payload,
                              auth=HTTPBasicAuth(username=sei_id, password=sei_secret))

if post_response.status_code == 201:
    do_delete = True
    response_json = post_response.json()
    pprint(response_json)

    exam_id = response_json['id']

    # go get the integration token that is required to make requests to /api/exams/<exam_id> endpoints
    print('Getting integration credentials')
    integration_url = 'https://sei.caveon.com/api/integrations/{exam_id}/credentials'.format(exam_id=exam_id)
    integration_response = requests.get(integration_url, auth=HTTPBasicAuth(username=sei_id, password=sei_secret))
    if integration_response.status_code == 200:
        integration_json = integration_response.json()
        pprint(integration_json)
        token = integration_json['token']
        delete_headers = {
            'Authorization': 'Bearer {0}'.format(token)
        }

        print('Deleting exam')
        delete_url = url + '/{exam_id}'.format(exam_id=exam_id)
        delete_response = requests.delete(delete_url, headers=delete_headers)
        if delete_response.status_code == 204:
            print('Successfully deleted exam. Have a good one!')
    else:
        print('Error getting integration credentials')

else:
    print('Error creating the exam. Your SEI id or secret is probably bad')
