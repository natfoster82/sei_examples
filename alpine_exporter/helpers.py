from datetime import datetime
from json import loads, dumps
from urllib.parse import quote_plus

import jwt
import requests
from redis import StrictRedis
from requests.auth import HTTPBasicAuth

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

    split_idx = 25
    empty_cand_values = ['' for x in range(20)]

    def __init__(self, exam_id, integration_info, type, start, end):
        self.exam_id = exam_id
        self.integration_info = integration_info
        self.type = type
        if self.type not in {'exam', 'cand', 'all'}:
            raise ValueError('type must be exam, cand, or all')
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

        # fetch exam
        exam_url = '{0}/api/exams/{1}?only=name'.format(SEI_URL_BASE, self.exam_id)
        exam_resp = requests.get(exam_url, headers=self.headers)
        self.exam_title = exam_resp.json()['name']
        self.exam_title = self.exam_title.replace('"', '')
        self.exam_title_escaped = '"{}"'.format(self.exam_title)
        self.exam_code = integration_info.get('exam_code') or ''.join([x[0].upper() for x in self.exam_title.split(' ')])
        self.last_timestamp = None

    def get_client_id(self, examinee_info):
        try:
            client_id = examinee_info['id']
        except KeyError:
            try:
                client_jwt = examinee_info['jwt']
                try:
                    decoded_jwt = jwt.decode(client_jwt, self.secret, algorithms=['HS256'])
                    client_id = decoded_jwt['id']
                except jwt.exceptions.InvalidTokenError:
                    if CHECK_SECRET:
                        raise InvalidSecretError
                    client_id = ''
            except KeyError:
                client_id = ''
        return client_id

    @staticmethod
    def trim_timestamp(timestamp):
        try:
            return timestamp.split('.')[0]
        except Exception:
            return ''

    @property
    def cand_columns(self):
        return self.all_columns[:self.split_idx]

    @property
    def exam_columns(self):
        return self.all_columns[self.split_idx:]

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
            delivery['form_id'],
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

    def all_values(self, delivery):
        return self.cand_values(delivery) + self.exam_values(delivery)

    @staticmethod
    def make_row(l):
        return ', '.join(l) + '\r\n'

    def generate(self):
        header = getattr(self, '{}_columns'.format(self.type))
        values_func = getattr(self, '{}_values'.format(self.type))

        yield header

        page = 0
        has_next = True

        base_url = '{0}/api/exams/{1}/deliveries?status=complete&sort=modified_at'.format(SEI_URL_BASE, self.exam_id)
        if self.start:
            base_url += '&modified_after={0}'.format(quote_plus(self.start))

        if self.end:
            base_url += '&modified_before={0}'.format(quote_plus(self.end))

        while has_next:
            page += 1
            url = base_url + '&page={0}'.format(str(page))
            r = requests.get(url, headers=self.headers)
            data = r.json()
            has_next = data['has_next']
            for delivery in data['results']:
                try:
                    values = values_func(delivery)
                except (InvalidSecretError, InvalidDeliveryError):
                    continue
                self.last_timestamp = delivery['modified_at']
                yield values

    def generate_csv(self):
        for l in self.generate():
            yield self.make_row(l)
