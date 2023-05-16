import json
import logging
import traceback
import sys
import os
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import threading
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer


def setup_logger(name):
    """
    setup logger
    """
    level = logging.INFO
    formatter = logging.Formatter("%(asctime)s:%(levelname)s:%(message)s")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)
    return logger


def full_stack():
    """
    log full error
    stack
    """
    exc = sys.exc_info()[0]
    stack = traceback.extract_stack()[:-1]  # last one would be full_stack()
    if exc is not None:  # i.e. an exception is present
        del stack[-1]  # remove call of full_stack, the printed exception
        # will contain the caught exception caller instead
    trc = 'Traceback (most recent call last):\n'
    stackstr = trc + ''.join(traceback.format_list(stack))
    if exc is not None:
        stackstr += '  ' + traceback.format_exc().lstrip(trc)
    return stackstr


class UptimeMonitor:
    """
    a class to perform monitoring,
    store data and aggregate results
    """

    def __init__(self, urls, dump_file, retention_time=60, check_period=30):
        """
        retention_time - how long store data, minutes
        check_period - how often check each endpoint, seconds
        """
        self.urls = urls
        self.pool = ThreadPoolExecutor(50)
        self.logger = setup_logger('logger')
        self.dump_file = dump_file

        self.retention_time = timedelta(minutes=retention_time)
        self.check_period = check_period

        self.data = {}
        # trying to restore data after crash:
        try:
            with open(self.dump_file) as f:
                js = json.load(f)
                self.data = self.json_to_data(js)
            # delete urls that could be in dump but not desired anymore
            durls = list(self.data.keys())
            for url in durls:
                if url not in self.urls:
                    del self.data[url]
        except Exception as e:
            self.logger.error('dump loading failed')
            self.logger.error(e)
            self.logger.error(full_stack())
        for url in urls:
            if url not in self.data:
                self.data[url] = {}

    def check_url(self, url):
        """
        perform a http query
        and save whether statuscode 200
        or not
        """
        res = 0
        try:
            r = requests.get(url, timeout=3)
            if r.status_code == 200:
                res = 1
        except Exception:
            pass
        # self.data[url][str(datetime.now()).split(".")[0]] = res
        self.data[url][datetime.now()] = res

    def delete_expired(self):
        """
        delete all the data points
        older than specified retention_time
        """

        now = datetime.now()
        for url, data in self.data.items():
            to_delete = []
            for t in data:
                if t + self.retention_time < now:
                    to_delete.append(t)
            for t in to_delete:
                del data[t]

    @staticmethod
    def json_to_data(j):
        """convert date from loaded
        json from str to datetime"""
        res = {}
        for url, data in j.items():
            res[url] = {}
            for st, value in data.items():
                st = datetime.strptime(st, '%Y-%m-%d %H:%M:%S')
                res[url][st] = value
        return res

    def data_to_json(self):
        """it is impossible to convert a dict
        with datetime as it is, so we have to convert
        it to datetime first"""
        res = {}
        for url, data in self.data.items():
            res[url] = {}
            for _datetime, value in data.items():
                res[url][str(_datetime).split(".")[0]] = value
        return res

    def dump_data(self):
        """ save data as json in case of
        service crash
        """
        with open(self.dump_file, 'w') as f:
            json.dump(self.data_to_json(), f)

    @staticmethod
    def calculate_uptime(l):
        """
        takes a list with zeros and ones,
        returns just a percentage of ones
        """
        total = len(l)
        ones = l.count(1)
        return round(ones / total * 100, 2)

    def uptime(self):
        """
        return dict with aggregated data
        to expose it as json via http
        """
        res = {}
        for url, data in self.data.items():
            res[url] = {'points_count': len(data),
                        'oldest': str(min(data.keys())),
                        'newest': str(max(data.keys())),
                        'uptime': self.calculate_uptime(list(data.values()))}
        return res

    def run(self):
        """
        do all the stuff in the loop
        """
        while True:
            self.logger.info('updating metrics')
            try:
                self.dump_data()
                self.delete_expired()
                for url in self.urls:
                    self.pool.submit(self.check_url, url)
                    # self.check_url(url)
            except Exception as e:
                self.logger.error(e)
                self.logger.error(full_stack())
            time.sleep(self.check_period)


class Server(BaseHTTPRequestHandler):
    """
    A HTTP server to expose data
    """

    def _set_headers(self, code):
        self.send_response(code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()

    def do_HEAD(self):
        """wtf"""
        self._set_headers(200)

    def do_GET(self):
        """execute on get"""
        if self.path == '/full':
            self._set_headers(200)
            self.wfile.write(json.dumps(monitor.data_to_json()).encode('utf-8'))
        if self.path == '/aggregated':
            self._set_headers(200)
            self.wfile.write(json.dumps(monitor.uptime()).encode('utf-8'))


def run_http_server(server_class=HTTPServer, handler_class=Server, port=80):
    """run http server"""
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)

    print('Starting http on port %d...' % port)
    httpd.serve_forever()


if __name__ == "__main__":
    urls_file = os.environ["URLS_FILE"]
    dump_file = os.environ["DUMP_FILE"]
    retention_time = int(os.environ["RETENTION_TIME"])
    check_period = int(os.environ["CHECK_PERIOD"])

    with open(urls_file) as f:
        urls = f.read().splitlines()

    monitor = UptimeMonitor(urls, dump_file,
                            retention_time=retention_time, check_period=check_period)

    threading.Thread(target=run_http_server, args=()).start()
    monitor.run()
