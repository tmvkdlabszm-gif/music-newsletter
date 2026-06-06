#!/usr/bin/env python3
"""
뉴스레터 폴더를 로컬 네트워크에 제공하는 작은 서버.
같은 와이파이의 폰/태블릿에서 http://<맥-IP>:8137/ 로 접속.
멀티스레드라 동시 요청에 멈추지 않는다. launchd가 상시 띄운다.
"""
import os
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

DIR = os.path.dirname(os.path.abspath(__file__))
PORT = 8137

handler = partial(SimpleHTTPRequestHandler, directory=DIR)
httpd = ThreadingHTTPServer(("0.0.0.0", PORT), handler)
print(f"serving {DIR} on 0.0.0.0:{PORT}")
httpd.serve_forever()
