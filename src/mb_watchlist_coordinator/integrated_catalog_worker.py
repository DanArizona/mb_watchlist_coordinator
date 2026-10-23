"""One public directory retrieval; no credential or broker interface."""
import base64
import json
import os
import socket
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

URLS = {'https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt',
        'https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt'}
MAX_BYTES = 4_000_000


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch(url):
    request = Request(url, headers={'User-Agent': 'mb_watchlist_coordinator bounded exact directory/1',
        'Accept': 'text/plain', 'Accept-Encoding': 'identity'})
    try:
        response = build_opener(ProxyHandler({}), NoRedirects()).open(request, timeout=3)
    except HTTPError as error:
        response = error
    with response:
        body = response.read(MAX_BYTES+1)
        if not 0 < len(body) <= MAX_BYTES:
            raise ValueError()
        return {'body_b64': base64.b64encode(body).decode(), 'status': response.getcode(),
            'final_url': response.geturl(), 'body_complete': True}


def main():
    job = json.load(sys.stdin)
    if job['url'] not in URLS or not .05 <= job['hard_seconds'] <= 10:
        return 70
    timer = threading.Timer(job['hard_seconds'], lambda: os._exit(124)); timer.daemon = True; timer.start()
    try:
        scenario = job['synthetic']
        if scenario is not None:
            def denied(*a, **kw): raise RuntimeError('Synthetic directory child denies network')
            socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = denied
            if scenario.get('hang'): time.sleep(60)
            if scenario.get('exit'): return 71
            result = {'body_b64': base64.b64encode(scenario['body'].encode()).decode(),
                'status': scenario.get('status', 200), 'final_url': scenario.get('final_url', job['url']),
                'body_complete': scenario.get('body_complete', True)}
        else:
            result = fetch(job['url'])
        print(json.dumps(result), flush=True)
        return 0
    except Exception:
        return 72  # No arbitrary transport/OS exception or URL content is echoed.
    finally:
        timer.cancel()


if __name__ == '__main__':
    raise SystemExit(main())
