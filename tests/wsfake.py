"""A WebSocket server for the tests: one thread, this machine only, speaking RFC 6455 from the server's side
(so wsclient's client side is tested against an independent reading of the standard), with a script a test
gives it for each connection. Not a test module."""
import base64, hashlib, socket, struct, threading, time

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def frame(opcode, payload=b"", fin=True):
    n = len(payload)
    head = bytes([(0x80 if fin else 0) | opcode])
    head += bytes([n]) if n < 126 else bytes([126]) + struct.pack(">H", n) if n < 65536 else bytes([127]) + struct.pack(">Q", n)
    return head + payload


class Peer:
    """One accepted connection: what the script talks to."""

    def __init__(self, sock, request):
        self.sock, self.request, self.buffer, self.closed, self.pings = sock, request, bytearray(), False, 0

    def send(self, text):
        self.sock.sendall(frame(0x1, text.encode()))

    def send_raw(self, data):
        self.sock.sendall(data)

    def send_parts(self, *texts):
        for i, text in enumerate(texts):
            self.sock.sendall(frame(0x1 if i == 0 else 0x0, text.encode(), fin=i == len(texts) - 1))

    def ping(self, payload=b"hi"):
        self.sock.sendall(frame(0x9, payload))

    def close(self):
        try:
            self.sock.sendall(frame(0x8, struct.pack(">H", 1000)))
        except OSError:
            pass

    def hang_up(self):
        self.closed = True
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()

    def recv(self, timeout=3.0):
        """The next text message the client sent (unmasked), a ("pong", payload) or ("close", code) tuple, or None."""
        deadline = time.monotonic() + timeout
        while True:
            b = self.buffer
            if len(b) >= 2:
                opcode, masked, n, i = b[0] & 0x0F, b[1] >> 7, b[1] & 0x7F, 2
                if n == 126 and len(b) >= 4:
                    n, i = struct.unpack(">H", bytes(b[2:4]))[0], 4
                elif n == 127 and len(b) >= 10:
                    n, i = struct.unpack(">Q", bytes(b[2:10]))[0], 10
                elif n in (126, 127):
                    n = None
                if n is not None and len(b) >= i + (4 if masked else 0) + n:
                    key = bytes(b[i:i + 4]) if masked else b""
                    i += 4 if masked else 0
                    payload = bytes(b[i:i + n])
                    del b[:i + n]
                    if masked:
                        payload = bytes(c ^ key[j % 4] for j, c in enumerate(payload))
                    if opcode == 0x1:
                        return payload.decode()
                    if opcode == 0xA:
                        return ("pong", payload)
                    if opcode == 0x8:
                        return ("close", struct.unpack(">H", payload[:2])[0] if len(payload) >= 2 else None)
                    if opcode == 0x9:
                        self.pings += 1
                        self.sock.sendall(frame(0xA, payload))
                    continue
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            self.sock.settimeout(left)
            try:
                data = self.sock.recv(65536)
            except socket.timeout:
                return None
            except OSError:
                self.closed = True
                return None
            if not data:
                self.closed = True
                return None
            self.buffer += data


class FakeServer:
    """Listens on 127.0.0.1; for each connection does the handshake and then runs `script(peer)` in a thread."""

    def __init__(self, script, bad_accept=False, status="101 Switching Protocols"):
        self.script, self.bad_accept, self.status = script, bad_accept, status
        self.listener = socket.socket()
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(8)
        self.port = self.listener.getsockname()[1]
        self.requests, self.peers, self.stopping = [], [], False
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.thread.start()

    def url(self, path="/", query=""):
        return f"ws://127.0.0.1:{self.port}{path}" + (f"?{query}" if query else "")

    def _accept(self):
        while not self.stopping:
            try:
                sock, _ = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(sock,), daemon=True).start()

    def _serve(self, sock):
        data = bytearray()
        sock.settimeout(5)
        try:
            while b"\r\n\r\n" not in data:
                chunk = sock.recv(4096)
                if not chunk:
                    return
                data += chunk
        except OSError:
            return
        head, _, rest = bytes(data).partition(b"\r\n\r\n")
        line, *fields = head.decode().split("\r\n")
        headers = {f.split(":", 1)[0].strip().lower(): f.split(":", 1)[1].strip() for f in fields}
        request = {"line": line, "path": line.split(" ")[1], "headers": headers}
        self.requests.append(request)
        accept = base64.b64encode(hashlib.sha1((headers.get("sec-websocket-key", "") + GUID).encode()).digest()).decode()
        if self.bad_accept:
            accept = "bm90IHRoZSByaWdodCBhbnN3ZXI="
        reply = (f"HTTP/1.1 {self.status}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                 f"Sec-WebSocket-Accept: {accept}\r\n\r\n")
        sock.sendall(reply.encode())
        peer = Peer(sock, request)
        peer.buffer += rest
        self.peers.append(peer)
        try:
            self.script(peer)
        except OSError:
            pass
        finally:
            if not peer.closed:
                try:
                    sock.close()
                except OSError:
                    pass

    def stop(self):
        self.stopping = True
        try:
            self.listener.close()
        except OSError:
            pass
        for peer in self.peers:
            try:
                peer.sock.close()
            except OSError:
                pass
