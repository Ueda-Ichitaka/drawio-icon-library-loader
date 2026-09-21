"""Test support: a small fake Chrome DevTools endpoint (HTTP discovery plus websocket) on a local port.

It exists so the websocket and DevTools client can be tested without starting an app.
"""

import base64
import hashlib
import json
import socket
import struct
import threading

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _read_exact(conn, count):
    data = b""
    while len(data) < count:
        chunk = conn.recv(count - len(data))
        if not chunk:
            raise ConnectionError("closed")
        data += chunk
    return data


def read_frame(conn):
    """Read one client frame; returns (opcode, payload) with the mask removed."""
    first, second = _read_exact(conn, 2)
    length = second & 0x7F
    if length == 126:
        length = struct.unpack(">H", _read_exact(conn, 2))[0]
    elif length == 127:
        length = struct.unpack(">Q", _read_exact(conn, 8))[0]
    mask = _read_exact(conn, 4) if second & 0x80 else None
    payload = _read_exact(conn, length)
    if mask:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return first & 0x0F, payload


def frame(opcode, payload, fin=True):
    """Build an unmasked server frame."""
    head = bytes([(0x80 if fin else 0) | opcode])
    if len(payload) < 126:
        head += bytes([len(payload)])
    elif len(payload) < 65536:
        head += bytes([126]) + struct.pack(">H", len(payload))
    else:
        head += bytes([127]) + struct.pack(">Q", len(payload))
    return head + payload


class FakeDevTools:
    """Serves /json/list, /json/version and websocket sessions answered by on_message.

    on_message(message: dict) returns the list of raw frames (bytes) to send back.
    """

    def __init__(self, targets=None, on_message=None):
        self.on_message = on_message or (lambda message: [])
        self.targets = targets
        self.received = []
        self.requests = []
        self._server = socket.socket()
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(5)
        self.port = self._server.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def close(self):
        self._server.close()

    def json_reply(self, message, *payloads):
        return [frame(1, json.dumps(p).encode()) for p in payloads]

    def _serve(self):
        while True:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        try:
            head = b""
            while b"\r\n\r\n" not in head:
                head += conn.recv(4096)
            lines = head.decode().split("\r\n")
            path = lines[0].split(" ")[1]
            headers = {k.lower(): v for k, v in (l.split(": ", 1) for l in lines[1:] if ": " in l)}
            self.requests.append((path, headers))
            if headers.get("upgrade", "").lower() == "websocket":
                accept = base64.b64encode(hashlib.sha1((headers["sec-websocket-key"] + _GUID).encode()).digest())
                conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                             b"Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept + b"\r\n\r\n")
                while True:
                    opcode, payload = read_frame(conn)
                    if opcode == 8:
                        return
                    message = json.loads(payload)
                    self.received.append((path, message))
                    for out in self.on_message(message):
                        conn.sendall(out)
            else:
                if path == "/json/list":
                    body = json.dumps(self.targets if self.targets is not None else []).encode()
                elif path == "/json/version":
                    body = json.dumps({"webSocketDebuggerUrl":
                                       "ws://127.0.0.1:%d/devtools/browser/abc" % self.port}).encode()
                else:
                    conn.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
                    return
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s"
                             % (len(body), body))
        except (ConnectionError, OSError):
            pass
        finally:
            conn.close()
