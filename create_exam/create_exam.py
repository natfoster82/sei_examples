import requests
from requests.auth import HTTPBasicAuth
from pprint import pprint


sei_id = input('What is your app\'s ID? ')
sei_secret = input('What is your app\'s secret? ')
exam_name = input('What do you want to call your exam? ')

url_base = 'https://sei.caveon.com'
post_url = url_base + '/api/exams'

payload = {
    'name': exam_name
}

print('Creating exam')
post_response = requests.post(post_url,
                              json=payload,
                              auth=HTTPBasicAuth(username=sei_id, password=sei_secret))

if post_response.status_code == 201:
    do_delete = True
    post_json = post_response.json()
    pprint(post_json)

    exam_id = post_json['id']

    # go get the integration token that is required to make requests to /api/exams/<exam_id> endpoints
    print('Getting integration credentials')
    integration_url = '{url_base}/api/integrations/{exam_id}/credentials'.format(url_base=url_base, exam_id=exam_id)
    integration_response = requests.get(integration_url, auth=HTTPBasicAuth(username=sei_id, password=sei_secret))
    integration_json = integration_response.json()
    pprint(integration_json)
    token = integration_json['token']
    headers = {
        'Authorization': 'Bearer {0}'.format(token)
    }

    print('Adding a description to the exam')
    put_url = post_url + '/{exam_id}'.format(exam_id=exam_id)
    description = input('Enter an exam description (default: "This is a description"): ') or 'This is a description'
    put_payload = {
        'settings': {
            'description': description
        }
    }
    put_response = requests.put(put_url, json=put_payload, headers=headers)
    if put_response.status_code == 200:
        put_json = put_response.json()
        pprint(put_json)
    else:
        print('Your app does not have edit_exam_settings permissions')

    print('Deleting the exam')
    # this only works because as the creating user for the exam, your app automatically has all permissions for the exam as long as the integration remains in place
    delete_url = put_url
    delete_response = requests.delete(delete_url, headers=headers)
    if delete_response.status_code == 204:
        print('Exam deleted')
    else:
        print('Error deleting the exam')
        pprint(delete_response.text)
else:
    print('Error creating the exam. Your SEI id or secret is probably bad')
