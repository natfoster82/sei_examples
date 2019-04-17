import codecs
import ftplib
from datetime import datetime
from json import loads, dumps
from urllib.parse import quote_plus

import jwt
import requests
from redis import StrictRedis
from requests.auth import HTTPBasicAuth
import async_request

from config import REDIS_URL, REDIS_DB, CHECK_SECRET, SEI_URL_BASE, SEI_ID, SEI_SECRET


redis_store = StrictRedis.from_url(REDIS_URL, db=REDIS_DB, decode_responses=True)
rq_store = StrictRedis.from_url(REDIS_URL, db=REDIS_DB)


def get_integration_info(exam_id):
    data = redis_store.get(exam_id)
    if data:
        return loads(data)
    url = SEI_URL_BASE + '/api/integrations/' + exam_id + '/credentials'
    resp = requests.get(url, auth=HTTPBasicAuth(username=SEI_ID, password=SEI_SECRET))
    if resp.status_code != 200:
        raise ValueError('No access to this exam_id')
    data = resp.json()
    redis_store.set(data['exam_id'], dumps(data))
    return data


class InvalidSecretError(Exception):
    pass


class InvalidDeliveryError(Exception):
    pass

def get_item_type(item_version):
    settings = item_version['settings']
    if settings['type'] == 'multiple_choice':
        if settings['points'] > 1 and settings['scoring'] == 'partial':
            return 'm'
        return 's'

def list_to_alpha(l, offset=65):
    alpha = []
    for index, value in enumerate(l):
        if value:
            letters = []
            while index >= 0:
                letters.append(chr(index % 25 + offset))
                index -= 25
            alpha.append(''.join(letters))
    return ''.join(alpha)

def item_response_to_alpha(item_response, item_version):
    final = item_response.get('final')
    content = item_version['content']

    if final is None:
        return ''

    response = []
    for index in range(len(content['options'])):
        if index in final:
            response.append(1)
        else:
            response.append(0)
    return list_to_alpha(response)

def get_item_status(item_response):
    score = item_response['score']
    if score is None or (score > 0 and score < 1):
        return 'a'

    if score == 1:
        return 'c'

    return 'i'

def as_safe_string(value):
    if value is None:
        return ''

    str_value = str(value)
    if ',' in str_value:
        return '"{str_value}"'.format(str_value=str_value)

    return str_value

class Exporter:
    all_columns = [
        'cand_id',
        'cand_client_id',
        'cand_last_update',
        'cand_name_first',
        'cand_name_last',
        'cand_email',
        'cand_company_name',
        'cand_addr1_line1',
        'cand_addr1_line2',
        'cand_addr1_line3',
        'cand_addr1_city',
        'cand_addr1_state',
        'cand_addr1_postal_code',
        'cand_addr1_country_code',
        'cand_addr1_phone_number',
        'cand_addr1_fax_number',
        'cand_loc_name_first',
        'cand_loc_name_last',
        'cand_loc_company_name',
        'cand_loc_addr1_line1',
        'cand_loc_addr1_line2',
        'cand_loc_addr1_line3',
        'cand_loc_addr1_city',
        'cand_loc_addr1_state',
        'cand_loc_addr1_postal_code',

        'exam_id',
        'exam_cand_id',
        'exam_code',
        'exam_test_center_id',
        'exam_date_time',
        'exam_time_spent',
        'exam_grade',
        'exam_score',
        'exam_rescored',
        'exam_passing_score',
        'exam_title',
        'exam_language_id',
        'exam_version',
        'exam_form',
        'exam_medium',
        'exam_items_correct',
        'exam_items_incorrect',
        'exam_items_skipped',
        'exam_auth_id',
        'exam_voucher_id',
        'exam_result_status',
        'exam_score_scaled'
    ]

    item_columns_ = [
        'item_exam_id',
        'item_name',
        'item_type',
        'item_status',
        'item_score',
        'item_time_spent',
        'item_response',
        'item_correct_answer',
        'item_section'
    ]

    split_idx = 25
    empty_cand_values = ['' for x in range(20)]

    def __init__(self, exam_id, integration_info, type, start, end):
        self.exam_id = exam_id
        self.integration_info = integration_info
        self.type = type
        if self.type not in {'exam', 'cand', 'all', 'item'}:
            raise ValueError('type must be exam, cand, item, or all')
        self.start = start
        self.end = end

        # set secret and headers from integration_info
        self.secret = integration_info.get('jwt_secret', 'invalid_secret')
        self.headers = {'Authorization': 'Bearer {0}'.format(integration_info['token'])}

        # set filename
        now = datetime.utcnow()
        self.filename = now.strftime('%Y%m%d-%H%M%S.csv')
        if type == 'cand':
            self.filename = 'cand-' + self.filename
        elif type == 'exam':
            self.filename = 'exam-' + self.filename
        elif type == 'item':
            self.filename = 'item-' + self.filename

        # fetch exam
        exam_url = '{0}/api/exams/{1}?only=name'.format(SEI_URL_BASE, self.exam_id)
        exam_resp = requests.get(exam_url, headers=self.headers)

        self.exam_title = exam_resp.json()['name']
        self.exam_title = self.exam_title.replace('"', '')
        self.exam_title_escaped = '"{}"'.format(self.exam_title)
        self.exam_code = integration_info.get('exam_code') or ''.join([x[0].upper() for x in self.exam_title.split(' ')])
        self.last_timestamp = None
        self.item_version_cache = {}

    def get_client_id(self, examinee_info):
        client_id = examinee_info.get('id')
        if client_id:
            return client_id
        if 'jwt' in examinee_info:
            client_jwt = examinee_info['jwt']
            try:
                decoded_jwt = jwt.decode(client_jwt, self.secret, algorithms=['HS256'])
                return decoded_jwt.get('Id', decoded_jwt.get('id', ''))
            except jwt.exceptions.InvalidTokenError:
                if CHECK_SECRET:
                    raise InvalidSecretError
                return ''
        return ''

    def trim_timestamp(self, timestamp):
        try:
            return timestamp.split('.')[0]
        except Exception:
            return ''

    def cand_columns(self):
        return self.all_columns[:self.split_idx]

    def exam_columns(self):
        return self.all_columns[self.split_idx:]

    def item_columns(self):
        return self.item_columns_

    def cand_values(self, delivery):
        client_id = self.get_client_id(delivery['examinee']['info'])
        values = [
            delivery['examinee_id'],
            client_id,
            self.trim_timestamp(delivery['created_at']),
            '?',
            '?'
        ]
        return values + self.empty_cand_values

    def exam_values(self, delivery):
        # check secret here to keep them in line
        self.get_client_id(delivery['examinee']['info'])
        exam_grade = 'p' if delivery['passed'] else 'f'
        score = str(delivery['score'])
        try:
            cutscore = str(delivery['cutscore']['score'])
        except KeyError:
            cutscore = ''

        try:
            items_correct = int(delivery['points_earned'])
            items_total = int(delivery['points_available'])
            items_incorrect = items_total - items_correct
        except TypeError:
            raise InvalidDeliveryError

        values = [
            delivery['id'],
            delivery['examinee_id'],
            self.exam_code,
            '',
            self.trim_timestamp(delivery['submitted_at']),
            str(int(delivery['used_seconds'])),
            exam_grade,
            score,
            str(int(bool(delivery['rescored_at']))),
            cutscore,
            self.exam_title_escaped,
            '',
            '',
            str(delivery['form_id']),
            '',
            str(items_correct),
            str(items_incorrect),
            '0',
            '',
            '',
            'OK',
            score
        ]
        return values

    def item_values(self, delivery):
        # check secret here to keep them in line
        self.get_client_id(delivery['examinee']['info'])

        item_responses = delivery['item_responses']
        values = []

        all_item_version_ids = [resp['item_version_id'] for resp in item_responses if resp['type'] == 'main']
        new_item_version_ids = [version_id for version_id in all_item_version_ids if version_id not in self.item_version_cache]
        ready_requests = []

        for item_version_id in new_item_version_ids:
            url = '{sei_url_base}/api/exams/{exam_id}/item_versions/{item_version_id}?include=item'\
                .format(sei_url_base=SEI_URL_BASE, exam_id=self.exam_id, item_version_id=item_version_id)
            ready_requests.append(url)

        if len(ready_requests) > 0:
            responses = async_request.map({ 'headers': self.headers }, ready_requests)
            responses_json = [item_version.json for item_version in responses]
            self.item_version_cache.update({ item_version['id']: item_version for item_version in responses_json })

        for item_response in item_responses:
            item_version = self.item_version_cache[item_response['item_version_id']]
            item = item_version['item']

            if item_version['settings']['type'] != 'multiple_choice':
                continue

            item_response['delivery_id'] = delivery['id']
            values.append(self.item_response_values(item, item_version, item_response))
        return values

    def item_response_values(self, item, item_version, item_response):
        item_exam_id = item_response['delivery_id']
        item_name = item_response['item_version_name']
        item_type = get_item_type(item_version)
        item_status = get_item_status(item_response)
        item_score = item_response['score']
        item_time_spent = int(round(item_response['seconds']))
        item_response_ = item_response_to_alpha(item_response, item_version)
        item_correct_answer = list_to_alpha(item_version['settings']['key'])
        item_section = item['content_area'].replace('|', ',')

        item_values = [
            item_exam_id,
            item_name,
            item_type,
            item_status,
            item_score,
            item_time_spent,
            item_response_,
            item_correct_answer,
            item_section
        ]

        return map(as_safe_string, item_values)

    def all_values(self, delivery):
        return self.cand_values(delivery) + self.exam_values(delivery) + self.item_values(delivery)

    def make_row(self, l):
        return ','.join(l) + '\r\n'

    def generate(self, get_buffer=None):
        page = 0
        has_next = True

        base_url = '{0}/api/exams/{1}/deliveries?status=complete&sort=modified_at&include=item_responses'.format(SEI_URL_BASE, self.exam_id)
        if self.start:
            base_url += '&modified_after={0}'.format(quote_plus(self.start))

        if self.end:
            base_url += '&modified_before={0}'.format(quote_plus(self.end))

        if self.type == 'all' or self.type == 'cand':
            cand_buffer = get_buffer('cand')
            yield cand_buffer.write(self.make_row(self.cand_columns()))
        
        if self.type == 'all' or self.type == 'exam':
            exam_buffer = get_buffer('exam')
            yield exam_buffer.write(self.make_row(self.exam_columns()))
        
        if self.type == 'all' or self.type == 'item':
            item_buffer = get_buffer('item')
            yield item_buffer.write(self.make_row(self.item_columns()))

        while has_next:
            page += 1
            url = base_url + '&page={0}'.format(str(page))
            r = requests.get(url, headers=self.headers)
            data = r.json()
            has_next = data['has_next']
            for delivery in data['results']:
                try:
                    if self.type == 'all' or self.type == 'cand':
                        yield cand_buffer.write(self.make_row(self.cand_values(delivery)))
                    
                    if self.type == 'all' or self.type == 'exam':
                        yield exam_buffer.write(self.make_row(self.exam_values(delivery)))
                    
                    if self.type == 'all' or self.type == 'item':
                        for response_row in self.item_values(delivery):
                            yield item_buffer.write(self.make_row(response_row))
                except (InvalidSecretError, InvalidDeliveryError):
                    continue
                self.last_timestamp = delivery['modified_at']

    def generate_csv(self, bom=False):
        if bom:
            yield codecs.BOM_UTF8

        def get_buffer(row_type):
            class ResponseBuffer:
                def write(self, row):
                    return row
            return ResponseBuffer()

        for row in self.generate(get_buffer=get_buffer):
            yield row


# copied from https://stackoverflow.com/questions/14659154/ftpes-session-reuse-required
# fixes some bug I'm not old enough to understand
class MyFTP_TLS(ftplib.FTP_TLS):
    """Explicit FTPS, with shared TLS session"""
    def ntransfercmd(self, cmd, rest=None):
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            conn = self.context.wrap_socket(conn,
                                            server_hostname=self.host,
                                            session=self.sock.session)  # this is the fix
        return conn, size
