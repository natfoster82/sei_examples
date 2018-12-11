import requests
from requests.auth import HTTPBasicAuth
from pprint import pprint
import os
from mimetypes import guess_type

# get credentials to post to the exam
sei_id = input('What is your app\'s ID? ')
sei_secret = input('What is your app\'s secret? ')
exam_id = input('What is your Exam ID? ')

# or uncomment these lines and hard code the values
# sei_id = '<app id here>'
# sei_secret = '<app secret here>'
# exam_id = '<exam id here>'

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
    post_json = post_response.json()
    pprint(post_json)
    print('')

    upload_url = post_json['upload_info']['url']
    upload_data = post_json['upload_info']['fields']
    upload_headers = {
        'x-amz-server-side-encryption': 'AES256'
    }
    upload_files = {'file': open(file_name, 'rb')}

    upload_response = requests.post(upload_url, files=upload_files, headers=upload_headers, data=upload_data)
    if upload_response.status_code == 204:
        print('Upload successful. Download your file here:')
        print(post_json['download_url'])

else:
    print('Error creating the file in SEI')
