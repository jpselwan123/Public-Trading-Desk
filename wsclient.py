"""A small WebSocket client (RFC 6455) over the standard library, for the live chart's trade streams
(stream.py; the owner, 5 Oct 2026: "tick by tick I need").

urllib cannot hold a WebSocket open, so this is the one place the desk opens a socket itself. It does
only what a stream needs: connect to ws:// or wss://, check the server's handshake, send text messages,
read text messages (answering pings, joining fragments), and close. It reads and writes nothing else,
sends the address's own query to the server and nowhere else, and never puts the address (which may
carry a key) in an error.

Not done, on purpose: a proxy tunnel, compression, binary messages as anything but text. A connection that
cannot be made is a WebSocketError, and the chart carries on with its polling.
"""
import base64, hashlib, os, socket, ssl, struct, threading, time, urllib.parse

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"       # RFC 6455, section 1.3
MAX_MESSAGE = 4 * 1024 * 1024
TEXT, BINARY, CONTINUE, CLOSE, PING, PONG = 0x1, 0x2, 0x0, 0x8, 0x9, 0xA


class WebSocketError(Exception):
    pass


class WebSocketRefused(WebSocketError):
    """The server answered the handshake with an HTTP status other than 101: `code` is that status."""

    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


def accept_key(key):
    return base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()


class Connection:
    def __init__(self, sock, leftover=b""):
        self.sock = sock
        self.buffer = bytearray(leftover)
        self.open = True
        self._parts, self._lock = [], threading.Lock()

    # ---- sending ------------------------------------------------------------------------------
    def _send(self, opcode, payload=b""):
        n = len(payload)
        head = bytes([0x80 | opcode])
        head += bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536 \
            else bytes([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)                                  # a client masks everything it sends
        body = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        try:
            with self._lock:
                self.sock.settimeout(10)
                self.sock.sendall(head + mask + body)
        except (OSError, ssl.SSLError) as e:
            self.open = False
            raise WebSocketError(f"the connection broke while sending ({type(e).__name__})") from None

    def send(self, text):
        self._send(TEXT, text.encode("utf-8"))

    def ping(self):
        self._send(PING, b"")

    def close(self):
        if self.open:
            try:
                self._send(CLOSE, struct.pack(">H", 1000))
            except WebSocketError:
                pass
        self.open = False
        try:
            self.sock.close()
        except OSError:
            pass

    # ---- reading ------------------------------------------------------------------------------
    def _frame(self):
        """One whole frame from the buffer, or None if it has not all come yet."""
        b = self.buffer
        if len(b) < 2:
            return None
        fin, opcode, masked, n, i = b[0] >> 7, b[0] & 0x0F, b[1] >> 7, b[1] & 0x7F, 2
        if n == 126:
            if len(b) < 4:
                return None
            n, i = struct.unpack(">H", bytes(b[2:4]))[0], 4
        elif n == 127:
            if len(b) < 10:
                return None
            n, i = struct.unpack(">Q", bytes(b[2:10]))[0], 10
        if n > MAX_MESSAGE:
            raise WebSocketError("the server sent a message that is too large")
        key = b""
        if masked:
            if len(b) < i + 4:
                return None
            key, i = bytes(b[i:i + 4]), i + 4
        if len(b) < i + n:
            return None
        payload = bytes(b[i:i + n])
        del b[:i + n]
        if masked:
            payload = bytes(c ^ key[j % 4] for j, c in enumerate(payload))
        return fin, opcode, payload

    def _read(self, timeout):
        """More bytes into the buffer; False if none came within `timeout`."""
        try:
            self.sock.settimeout(timeout)
            data = self.sock.recv(65536)
        except socket.timeout:
            return False
        except (OSError, ssl.SSLError) as e:
            self.open = False
            raise WebSocketError(f"the connection broke ({type(e).__name__})") from None
        if not data:
            self.open = False
            raise WebSocketError("the server closed the connection")
        self.buffer += data
        return True

    def recv(self, timeout=1.0):
        """The next text message, or None if none came within `timeout` seconds. Pings are answered here,
        fragments joined; a close or a broken connection raises WebSocketError."""
        deadline = time.monotonic() + timeout
        while True:
            frame = self._frame()
            if frame is None:
                left = deadline - time.monotonic()
                if left <= 0 or not self._read(max(0.01, left)):
                    return None
                continue
            fin, opcode, payload = frame
            if opcode == PING:
                self._send(PONG, payload)
            elif opcode == PONG:
                pass
            elif opcode == CLOSE:
                self.open = False
                try:
                    self._send(CLOSE, payload[:2])
                except WebSocketError:
                    pass
                raise WebSocketError("the server closed the connection")
            elif opcode in (TEXT, BINARY, CONTINUE):
                if opcode != CONTINUE:
                    self._parts = []
                self._parts.append(payload)
                if sum(len(p) for p in self._parts) > MAX_MESSAGE:
                    raise WebSocketError("the server sent a message that is too large")
                if fin:
                    whole, self._parts = b"".join(self._parts), []
                    return whole.decode("utf-8", "replace")
            else:
                raise WebSocketError("the server sent a frame this client does not know")


def connect(url, timeout=15, headers=None):
    """A Connection to a ws:// or wss:// address, its handshake checked."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("ws", "wss") or not parts.hostname:
        raise WebSocketError("not a WebSocket address")
    secure, host = parts.scheme == "wss", parts.hostname
    port = parts.port or (443 if secure else 80)
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        if secure:
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
    except (OSError, ssl.SSLError) as e:
        raise WebSocketError(f"can't reach {host} ({type(e).__name__})") from None
    key = base64.b64encode(os.urandom(16)).decode()
    path = (parts.path or "/") + ("?" + parts.query if parts.query else "")
    lines = [f"GET {path} HTTP/1.1", f"Host: {host}" + (f":{parts.port}" if parts.port else ""), "Upgrade: websocket",
             "Connection: Upgrade", f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13", "User-Agent: trading-desk"]
    lines += [f"{k}: {v}" for k, v in (headers or {}).items()]
    try:
        sock.settimeout(timeout)
        sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        reply = bytearray()
        deadline = time.monotonic() + timeout
        while b"\r\n\r\n" not in reply:
            if time.monotonic() > deadline or len(reply) > 16384:
                raise WebSocketError(f"{host} did not finish the handshake")
            data = sock.recv(4096)
            if not data:
                raise WebSocketError(f"{host} closed the connection during the handshake")
            reply += data
    except WebSocketError:
        sock.close()
        raise
    except (OSError, ssl.SSLError) as e:
        sock.close()
        raise WebSocketError(f"the handshake with {host} broke ({type(e).__name__})") from None
    head, _, rest = bytes(reply).partition(b"\r\n\r\n")
    status, *fields = head.decode("latin-1").split("\r\n")
    got = {line.split(":", 1)[0].strip().lower(): line.split(":", 1)[1].strip() for line in fields if ":" in line}
    if status.split(" ")[1:2] != ["101"]:
        sock.close()
        code = status.split(" ")[1] if len(status.split(" ")) > 1 else ""
        raise WebSocketRefused(f"{host} refused the WebSocket ({status[:60]})", int(code) if code.isdigit() else 0)
    if got.get("sec-websocket-accept") != accept_key(key):
        sock.close()
        raise WebSocketError(f"{host} gave a handshake this client cannot trust")
    return Connection(sock, rest)
