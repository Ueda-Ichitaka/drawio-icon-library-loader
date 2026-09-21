"""A minimal Chrome DevTools Protocol client using only the standard library.

Just enough of RFC 6455 (client text frames, reassembly, ping/pong) to run JavaScript in the
draw.io window and to close the app, so the loader needs no third-party websocket package.
"""

import base64
import hashlib
import json
import os
import socket
import struct
import time
import urllib.request
from urllib.parse import urlparse

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_EVAL_ID = 1


class CdpError(Exception):
    """The DevTools endpoint could not be reached, timed out or reported an error."""


def find_free_port():
    """Return a TCP port on the loopback interface that is currently unused."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class _WebSocket:
    def __init__(self, url, deadline, clock):
        self._deadline = deadline
        self._clock = clock
        self._buffer = b""
        parts = urlparse(url)
        try:
            self._sock = socket.create_connection((parts.hostname, parts.port),
                                                  timeout=max(0.1, deadline - clock()))
            self._handshake(parts)
        except OSError as error:
            raise CdpError("cannot connect to %s: %s" % (url, error))

    def _handshake(self, parts):
        key = base64.b64encode(os.urandom(16)).decode()
        request = ("GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                   "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n"
                   % (parts.path or "/", parts.hostname, parts.port, key))
        self._sock.sendall(request.encode())
        while b"\r\n\r\n" not in self._buffer:
            self._fill()
        head, _, self._buffer = self._buffer.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        headers = {k.lower(): v for k, v in (l.split(": ", 1) for l in lines[1:] if ": " in l)}
        expected = base64.b64encode(hashlib.sha1((key + _GUID).encode()).digest()).decode()
        if " 101 " not in lines[0] or headers.get("sec-websocket-accept") != expected:
            raise OSError("websocket handshake refused: " + lines[0])

    def _fill(self):
        remaining = self._deadline - self._clock()
        if remaining <= 0:
            raise socket.timeout("timed out")
        self._sock.settimeout(remaining)
        chunk = self._sock.recv(65536)
        if not chunk:
            raise ConnectionError("connection closed")
        self._buffer += chunk

    def _read(self, count):
        while len(self._buffer) < count:
            self._fill()
        data, self._buffer = self._buffer[:count], self._buffer[count:]
        return data

    def _send_frame(self, opcode, payload):
        head = bytes([0x80 | opcode])
        if len(payload) < 126:
            head += bytes([0x80 | len(payload)])
        elif len(payload) < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", len(payload))
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", len(payload))
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        self._sock.sendall(head + mask + masked)

    def send_text(self, text):
        try:
            self._send_frame(1, text.encode())
        except OSError as error:
            raise CdpError("cannot send: %s" % error)

    def recv_text(self):
        message = b""
        try:
            while True:
                first, second = self._read(2)
                length = second & 0x7F
                if length == 126:
                    length = struct.unpack(">H", self._read(2))[0]
                elif length == 127:
                    length = struct.unpack(">Q", self._read(8))[0]
                payload = self._read(length)
                opcode = first & 0x0F
                if opcode == 8:
                    raise CdpError("connection closed by the app")
                if opcode == 9:
                    self._send_frame(10, payload)
                elif opcode in (0, 1, 2):
                    message += payload
                    if first & 0x80:
                        return message.decode()
        except OSError as error:
            raise CdpError("connection failed: %s" % error)

    def close(self):
        try:
            self._send_frame(8, b"")
        except OSError:
            pass
        self._sock.close()


def evaluate(ws_url, expression, timeout=30, clock=time.monotonic):
    """Run JavaScript in the target behind ws_url and return the resulting value."""
    socket_ = _WebSocket(ws_url, clock() + timeout, clock)
    try:
        socket_.send_text(json.dumps({"id": _EVAL_ID, "method": "Runtime.evaluate", "params": {
            "expression": expression, "returnByValue": True, "awaitPromise": True}}))
        while True:
            message = json.loads(socket_.recv_text())
            if message.get("id") == _EVAL_ID:
                break
    finally:
        socket_.close()
    if "error" in message:
        raise CdpError(message["error"].get("message", "protocol error"))
    outcome = message["result"]
    if "exceptionDetails" in outcome:
        details = outcome["exceptionDetails"]
        raise CdpError("script failed: " + (details.get("exception", {}).get("description")
                                            or details.get("text", "unknown error")))
    return outcome["result"].get("value")


def _get_json(port, path):
    with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=2) as response:
        return json.load(response)


def find_page(port, timeout, sleep=time.sleep, clock=time.monotonic):
    """Wait until the draw.io editor page is listed by the DevTools endpoint on port and return its target."""
    deadline = clock() + timeout
    while True:
        try:
            for target in _get_json(port, "/json/list"):
                if target.get("type") == "page" and "index.html" in target.get("url", ""):
                    return target
        except (OSError, ValueError):
            pass
        if clock() >= deadline:
            raise CdpError("draw.io did not open its window within %ds" % timeout)
        sleep(0.5)


def close_browser(port, timeout=10, clock=time.monotonic):
    """Ask the app behind port to shut down cleanly; an endpoint that is already gone is fine."""
    try:
        url = _get_json(port, "/json/version")["webSocketDebuggerUrl"]
        socket_ = _WebSocket(url, clock() + timeout, clock)
    except (OSError, ValueError, KeyError, CdpError):
        return
    try:
        socket_.send_text(json.dumps({"id": _EVAL_ID, "method": "Browser.close"}))
        socket_.recv_text()
    except CdpError:
        pass
    finally:
        socket_.close()
