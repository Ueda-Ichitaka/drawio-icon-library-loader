"""Tests for drawio_libs.cdp: the stdlib websocket client and the DevTools calls built on it."""

import json
import unittest

from drawio_libs.cdp import CdpError, close_browser, evaluate, find_free_port, find_page
from tests.fake_devtools import FakeDevTools, frame


def result(message, value):
    return frame(1, json.dumps({"id": message["id"], "result": {"result": {"type": "string", "value": value}}}).encode())


class EvaluateTest(unittest.TestCase):
    def setUp(self):
        self.server = FakeDevTools()
        self.addCleanup(self.server.close)

    def ws_url(self, path="/devtools/page/p1"):
        return "ws://127.0.0.1:%d%s" % (self.server.port, path)

    def test_returns_the_value_of_the_expression(self):
        self.server.on_message = lambda m: [result(m, "42")]
        self.assertEqual(evaluate(self.ws_url(), "1+1"), "42")

    def test_sends_runtime_evaluate_that_returns_by_value_and_awaits_promises(self):
        self.server.on_message = lambda m: [result(m, "x")]
        evaluate(self.ws_url(), "expr()")
        _, message = self.server.received[0]
        self.assertEqual(message["method"], "Runtime.evaluate")
        self.assertEqual(message["params"], {"expression": "expr()", "returnByValue": True, "awaitPromise": True})

    def test_the_handshake_sends_no_origin_header(self):
        self.server.on_message = lambda m: [result(m, "x")]
        evaluate(self.ws_url(), "1")
        _, headers = self.server.requests[0]
        self.assertNotIn("origin", headers)

    def test_events_before_the_response_are_skipped(self):
        event = frame(1, json.dumps({"method": "Runtime.consoleAPICalled", "params": {}}).encode())
        self.server.on_message = lambda m: [event, result(m, "done")]
        self.assertEqual(evaluate(self.ws_url(), "1"), "done")

    def test_a_response_split_across_frames_is_reassembled(self):
        def split(message):
            raw = json.dumps({"id": message["id"], "result": {"result": {"value": "joined"}}}).encode()
            return [frame(1, raw[:10], fin=False), frame(0, raw[10:])]
        self.server.on_message = split
        self.assertEqual(evaluate(self.ws_url(), "1"), "joined")

    def test_large_responses_use_extended_length_frames(self):
        big = "x" * 70000
        self.server.on_message = lambda m: [result(m, big)]
        self.assertEqual(evaluate(self.ws_url(), "1"), big)

    def test_large_requests_are_sent_with_extended_length(self):
        self.server.on_message = lambda m: [result(m, "ok")]
        evaluate(self.ws_url(), "'" + "y" * 70000 + "'")
        self.assertEqual(len(self.server.received[0][1]["params"]["expression"]), 70002)

    def test_a_javascript_exception_raises_cdp_error(self):
        def failing(message):
            body = {"id": message["id"], "result": {"result": {"type": "object"},
                    "exceptionDetails": {"text": "Uncaught", "exception": {"description": "ReferenceError: nope"}}}}
            return [frame(1, json.dumps(body).encode())]
        self.server.on_message = failing
        with self.assertRaises(CdpError) as caught:
            evaluate(self.ws_url(), "nope")
        self.assertIn("ReferenceError: nope", str(caught.exception))

    def test_a_protocol_error_raises_cdp_error(self):
        self.server.on_message = lambda m: [frame(1, json.dumps(
            {"id": m["id"], "error": {"code": -32601, "message": "no such method"}}).encode())]
        with self.assertRaises(CdpError) as caught:
            evaluate(self.ws_url(), "1")
        self.assertIn("no such method", str(caught.exception))

    def test_a_server_that_never_answers_times_out(self):
        self.server.on_message = lambda m: []
        with self.assertRaises(CdpError):
            evaluate(self.ws_url(), "1", timeout=0.3)

    def test_an_unreachable_endpoint_raises_cdp_error(self):
        with self.assertRaises(CdpError):
            evaluate("ws://127.0.0.1:%d/x" % find_free_port(), "1", timeout=0.5)


class FindPageTest(unittest.TestCase):
    def setUp(self):
        self.server = FakeDevTools()
        self.addCleanup(self.server.close)

    def test_returns_the_page_target_showing_the_editor(self):
        self.server.targets = [
            {"type": "service_worker", "url": "x/index.html", "webSocketDebuggerUrl": "ws://bad"},
            {"type": "page", "url": "file:///app/index.html?x=1", "webSocketDebuggerUrl": "ws://good"},
        ]
        self.assertEqual(find_page(self.server.port, timeout=2)["webSocketDebuggerUrl"], "ws://good")

    def test_waits_until_the_page_appears(self):
        polls = []
        clock = [0.0]

        def sleep(seconds):
            polls.append(seconds)
            clock[0] += seconds
            if len(polls) == 2:
                self.server.targets = [{"type": "page", "url": "file:///index.html", "webSocketDebuggerUrl": "ws://late"}]

        page = find_page(self.server.port, timeout=30, sleep=sleep, clock=lambda: clock[0])
        self.assertEqual(page["webSocketDebuggerUrl"], "ws://late")

    def test_gives_up_after_the_timeout(self):
        clock = [0.0]

        def sleep(seconds):
            clock[0] += seconds

        with self.assertRaises(CdpError):
            find_page(self.server.port, timeout=3, sleep=sleep, clock=lambda: clock[0])

    def test_a_port_nobody_listens_on_keeps_polling_until_timeout(self):
        clock = [0.0]

        def sleep(seconds):
            clock[0] += seconds

        with self.assertRaises(CdpError):
            find_page(find_free_port(), timeout=2, sleep=sleep, clock=lambda: clock[0])


class CloseBrowserTest(unittest.TestCase):
    def test_asks_the_browser_endpoint_to_close(self):
        server = FakeDevTools(on_message=lambda m: [frame(1, json.dumps({"id": m["id"], "result": {}}).encode())])
        self.addCleanup(server.close)
        close_browser(server.port)
        path, message = server.received[0]
        self.assertEqual(path, "/devtools/browser/abc")
        self.assertEqual(message["method"], "Browser.close")

    def test_an_endpoint_that_is_already_gone_is_not_an_error(self):
        close_browser(find_free_port())


if __name__ == "__main__":
    unittest.main()
