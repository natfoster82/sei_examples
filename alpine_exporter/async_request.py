from requests_futures.sessions import FuturesSession


def json_response_hook(resp, *args, **kwargs):
    resp.json = resp.json()

def map(session_options, resources):
    with FuturesSession(max_workers=4) as session:
        session.headers = session_options.get('headers')

        futures = [session.get(resource, hooks={'response': json_response_hook})\
            for resource in resources]
        results = [future.result() for future in futures]
        return results
