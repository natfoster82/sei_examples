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
    post_json = post_response.json()
    pprint(post_json)

    exam_id = post_json['id']

    # go get the integration token that is required to make requests to /api/exams/<exam_id> endpoints
    print('Getting integration credentials')
    integration_url = 'https://sei.caveon.com/api/integrations/{exam_id}/credentials'.format(exam_id=exam_id)
    integration_response = requests.get(integration_url, auth=HTTPBasicAuth(username=sei_id, password=sei_secret))
    integration_json = integration_response.json()
    pprint(integration_json)
    token = integration_json['token']
    put_headers = {
        'Authorization': 'Bearer {0}'.format(token)
    }

    print('Adding a description to the exam')
    put_url = url + '/{exam_id}'.format(exam_id=exam_id)
    description = input('Enter an exam description (default: "This is a description"): ') or 'This is a description'
    put_payload = {
        'settings': {
            'description': description
        }
    }
    put_response = requests.put(put_url, json=put_payload, headers=put_headers)
    if put_response.status_code == 200:
        put_json = put_response.json()
        pprint(put_json)
    else:
        print('Your app does not have edit_exam_settings permissions')

    print('Deleting the exam')
    # this only works because as the creating user for the exam, your app also has an admin role for the exam
    # notice how we authenticate using Basic instead of using the integration bearer token
    # when we authenticate this way, we get the permissions of our app's role as admin rather than our app's requested permission for an integration
    # app's do however need the x-role-secret header
    delete_headers = {
        'x-sei-role-secret': post_json['creating_role']['secret']
    }
    delete_url = put_url
    delete_response = requests.delete(delete_url,
                                      auth=HTTPBasicAuth(username=sei_id, password=sei_secret),
                                      headers=delete_headers)
    if delete_response.status_code == 204:
        print('Exam deleted')
    else:
        print('Error deleting the exam')
else:
    print('Error creating the exam. Your SEI id or secret is probably bad')
