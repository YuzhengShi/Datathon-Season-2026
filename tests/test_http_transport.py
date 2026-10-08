"""The real HTTP transport against a local server (no internet): what it must and must not do.

Needs the pinned stack. The loopback server is only used to exercise ``HttpxTransport``; the fetcher's own policy
(which refuses loopback addresses) is checked at the end with the same real transport.
"""

import gzip
import socket
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tests.support import requires_web_stack

HTML = b"<html><body><main><h1>Hello</h1></main></body></html>"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep test output quiet
        pass

    def send_body(self, body, status=200, headers=None):
        self.send_response(status)
        for key, value in {
            "Content-Type": "text/html; charset=utf-8",
            "Content-Length": str(len(body)),
            **(headers or {}),
        }.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        self.server.hits.append(self.path)
        if self.path == "/ok":
            self.send_body(HTML, headers={"ETag": '"v1"'})
        elif self.path == "/redirect":
            self.send_body(b"", status=302, headers={"Location": "/ok"})
        elif self.path == "/big":
            self.send_body(b"x" * 200_000)
        elif self.path == "/streamed":  # no Content-Length: the connection is closed to mark the end
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            for _ in range(200):
                self.wfile.write(b"y" * 1000)
        elif self.path == "/bomb":
            packed = gzip.compress(b"0" * 5_000_000)
            self.send_body(packed, headers={"Content-Encoding": "gzip"})
        elif self.path == "/gzip":
            self.send_body(gzip.compress(HTML), headers={"Content-Encoding": "gzip"})
        elif self.path == "/slow":
            time.sleep(2.0)
            self.send_body(HTML)
        else:
            self.send_body(b"missing", status=404)


@requires_web_stack
class HttpxTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import httpx

        from navigator.ingestion.http_transport import HttpxTransport

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server.hits = []
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.transport = HttpxTransport(httpx.Client(follow_redirects=False, trust_env=False))

    @classmethod
    def tearDownClass(cls):
        cls.transport.close()
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path, max_bytes=100_000, timeout=5.0):
        return self.transport.get(self.base + path, {"User-Agent": "test"}, timeout, max_bytes)

    def error_kind(self, path, **kw):
        from navigator.ingestion.fetcher import TransportError

        with self.assertRaises(TransportError) as caught:
            self.get(path, **kw)
        return caught.exception.kind

    def test_ok_response_has_lowercase_headers_and_the_body(self):
        response = self.get("/ok")
        self.assertEqual((response.status, response.body), (200, HTML))
        self.assertEqual(response.headers["content-type"], "text/html; charset=utf-8")
        self.assertEqual(response.headers["etag"], '"v1"')
        self.assertTrue(response.url.endswith("/ok"))

    def test_redirects_are_not_followed_the_fetcher_decides(self):
        before = len(self.server.hits)
        response = self.get("/redirect")
        self.assertEqual((response.status, response.headers["location"]), (302, "/ok"))
        self.assertEqual(
            self.server.hits[before:], ["/redirect"]
        )  # the target /ok was never requested by the transport

    def test_a_declared_size_over_the_limit_is_rejected(self):
        self.assertEqual(self.error_kind("/big", max_bytes=10_000), "too_large")

    def test_a_streamed_body_is_cut_off_at_the_limit(self):
        self.assertEqual(self.error_kind("/streamed", max_bytes=50_000), "too_large")

    def test_the_limit_applies_after_decompression(self):
        self.assertEqual(
            self.error_kind("/bomb", max_bytes=1_000_000), "too_large"
        )  # a few KB on the wire, 5 MB decoded
        self.assertEqual(self.get("/gzip").body, HTML)  # normal compressed responses still work

    def test_timeout_and_refused_connection_are_distinct_errors(self):
        self.assertEqual(self.error_kind("/slow", timeout=0.4), "timeout")
        from navigator.ingestion.fetcher import TransportError

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            free_port = probe.getsockname()[1]
        with self.assertRaises(TransportError) as caught:
            self.transport.get(f"http://127.0.0.1:{free_port}/", {}, 2.0, 1000)
        # Windows retries a refused loopback connection for about two seconds, so a short timeout can fire first;
        # either way the fetcher treats both kinds the same (bounded retry), and neither hangs.
        self.assertIn(caught.exception.kind, {"connect", "timeout"})

    def test_the_real_fetcher_refuses_loopback_before_sending_anything(self):
        from navigator.core.urlpolicy import AllowRule
        from navigator.ingestion.fetcher import Fetcher, FetchPolicy
        from navigator.ingestion.http_transport import system_resolver

        fetcher = Fetcher(self.transport, FetchPolicy("test"), resolver=system_resolver)
        before = len(self.server.hits)
        outcome = fetcher.fetch(self.base + "/ok", [AllowRule(("127.0.0.1",), ("/",))])
        # the ephemeral port is rejected first; the loopback address itself is rejected on a standard port
        self.assertEqual((outcome.outcome, outcome.reason), ("blocked", "url_port_not_allowed"))
        outcome = fetcher.fetch("http://127.0.0.1/ok", [AllowRule(("127.0.0.1",), ("/",))])
        self.assertEqual((outcome.outcome, outcome.reason), ("blocked", "url_private_address"))
        self.assertEqual(len(self.server.hits), before)  # not a single request reached the server


if __name__ == "__main__":
    unittest.main()
