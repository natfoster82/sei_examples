import requests
from requests.auth import HTTPBasicAuth
from pprint import pprint
import os
from mimetypes import guess_type

# get credentials to post to the exam
# sei_id = input('What is your app\'s ID? ')
# sei_secret = input('What is your app\'s secret? ')
# exam_id = input('What is your Exam ID? ')

# or hardcode them
sei_id = 'aeb1ab96-47c8-4d06-8170-0b9a548628c3'
sei_secret = '5805a47f1dfa391d8ed809eb59a91b48'
exam_id = '84b20449-d850-470e-a510-476e4ff748a1'

url_base = 'https://sei.caveon.com'

print('Getting integration credentials')
integration_url = '{0}/api/integrations/{1}/credentials'.format(url_base, exam_id)
integration_response = requests.get(integration_url, auth=HTTPBasicAuth(username=sei_id, password=sei_secret))
integration_json = integration_response.json()
pprint(integration_json)
print('')

token = integration_json['token']
post_url = '{0}/api/exams/{1}/files'.format(url_base, exam_id)
post_headers = {
    'Authorization': 'Bearer {0}'.format(token),
    'Content-Type': 'application/json'
}

print('building file post payload')
file_name = 'donut.jpg'
file_size = os.path.getsize(file_name)
file_type = guess_type(file_name)[0]

post_payload = {
    'name': file_name,
    'size': file_size,
    'type': file_type
}
pprint(post_payload)
print('')

print('Creating file object in SEI')
post_response = requests.post(post_url, json=post_payload, headers=post_headers)

if post_response.status_code == 201:
    do_delete = True
    post_json = post_response.json()
    pprint(post_json)

else:
    print('Error creating the file in SEI')
