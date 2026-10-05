"""wsclient: the WebSocket client (RFC 6455) against a server written from the other side of the standard.
Every connection is to this machine."""
from support import *  # noqa: F401,F403
import wsclient  # noqa: E402
import wsfake  # noqa: E402


class WebSocketClientTests(unittest.TestCase):
    def serve(self, script, **kw):
        server = wsfake.FakeServer(script, **kw)
        self.addCleanup(server.stop)
        return server

    def test_the_handshake_is_checked_and_what_the_server_sends_is_read(self):
        server = self.serve(lambda p: (p.send("hello"), p.recv(1)))
        conn = wsclient.connect(server.url("/v2/iex", "token=SECRET"), headers={"X-Test": "yes"})
        self.addCleanup(conn.close)
        self.assertEqual(conn.recv(2), "hello")
        request = server.requests[0]
        self.assertEqual(request["path"], "/v2/iex?token=SECRET")                      # the address's own query goes to the server
        self.assertEqual(request["headers"]["upgrade"], "websocket")
        self.assertEqual(request["headers"]["sec-websocket-version"], "13")
        self.assertEqual(request["headers"]["x-test"], "yes")
        self.assertEqual(len(base64.b64decode(request["headers"]["sec-websocket-key"])), 16)

    def test_a_bad_handshake_is_refused_and_no_error_carries_the_address(self):
        for kw, words in (({"bad_accept": True}, "cannot trust"), ({"status": "403 Forbidden"}, "refused")):
            server = self.serve(lambda p: None, **kw)
            with self.assertRaises(wsclient.WebSocketError) as e:
                wsclient.connect(server.url("/", "token=TOPSECRET"), timeout=3)
            self.assertIn(words, str(e.exception))
            self.assertNotIn("TOPSECRET", str(e.exception))
        with self.assertRaises(wsclient.WebSocketError) as e:
            wsclient.connect("ws://127.0.0.1:9/?token=TOPSECRET", timeout=2)                # nothing listens there
        self.assertNotIn("TOPSECRET", str(e.exception))
        for bad in ("http://127.0.0.1/", "ws:///x", "nonsense"):
            with self.assertRaises(wsclient.WebSocketError):
                wsclient.connect(bad)

    def test_what_the_client_sends_is_masked_and_whole_at_any_size(self):
        got = []

        def script(peer):
            for _ in range(3):
                got.append(peer.recv(3))
        server = self.serve(script)
        conn = wsclient.connect(server.url())
        self.addCleanup(conn.close)
        sizes = ("x" * 5, "y" * 300, "z" * 70000)                                          # the 7-bit, 16-bit and 64-bit lengths
        for text in sizes:
            conn.send(text)
        deadline = time.time() + 5
        while len(got) < 3 and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(got, list(sizes))

    def test_big_messages_fragments_and_pings_are_handled_without_losing_a_byte(self):
        big = "é" * 40000
        answered = []
        server = self.serve(lambda p: (p.send(big), p.ping(b"are you there"), p.send_parts("one ", "two ", "three"),
                                       p.send("after"), answered.append(p.recv(2))))
        conn = wsclient.connect(server.url())
        self.addCleanup(conn.close)
        self.assertEqual(conn.recv(3), big)
        self.assertEqual(conn.recv(3), "one two three")                                     # the ping between was answered, the parts joined
        self.assertEqual(conn.recv(3), "after")
        deadline = time.time() + 3
        while not answered and time.time() < deadline:
            time.sleep(0.02)
        self.assertEqual(answered, [("pong", b"are you there")])

    def test_a_pause_returns_none_and_a_frame_split_across_pauses_is_not_lost(self):
        whole = wsfake.frame(0x1, b'{"T":"t","p":131.4}')

        def script(peer):
            peer.send_raw(whole[:5])
            time.sleep(0.4)
            peer.send_raw(whole[5:])
            time.sleep(0.2)
        server = self.serve(script)
        conn = wsclient.connect(server.url())
        self.addCleanup(conn.close)
        self.assertIsNone(conn.recv(0.15))                                                   # only part has come
        text = None
        deadline = time.time() + 3
        while text is None and time.time() < deadline:
            text = conn.recv(0.2)
        self.assertEqual(text, '{"T":"t","p":131.4}')
        self.assertTrue(conn.open)

    def test_a_close_or_a_hang_up_raises_and_marks_it_closed(self):
        server = self.serve(lambda p: (p.send("bye"), p.close(), time.sleep(0.2)))
        conn = wsclient.connect(server.url())
        self.assertEqual(conn.recv(2), "bye")
        with self.assertRaises(wsclient.WebSocketError) as e:
            conn.recv(2)
        self.assertIn("closed", str(e.exception))
        self.assertFalse(conn.open)
        server = self.serve(lambda p: p.hang_up())
        conn = wsclient.connect(server.url())
        with self.assertRaises(wsclient.WebSocketError):
            conn.recv(2)
        with self.assertRaises(wsclient.WebSocketError):
            conn.send("into the dark")
            conn.send("again")
        self.assertFalse(conn.open)

    def test_the_client_closes_politely(self):
        server = self.serve(lambda p: setattr(p, "answer", p.recv(2)))
        conn = wsclient.connect(server.url())
        conn.close()
        deadline = time.time() + 2
        while not hasattr(server.peers[0], "answer") and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(server.peers[0].answer, ("close", 1000))

    def test_the_accept_key_is_the_standards(self):
        self.assertEqual(wsclient.accept_key("dGhlIHNhbXBsZSBub25jZQ=="), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")      # RFC 6455, section 1.3

    def test_a_message_over_the_limit_is_refused(self):
        server = self.serve(lambda p: (p.send_raw(bytes([0x81, 127]) + (wsclient.MAX_MESSAGE + 1).to_bytes(8, "big")), time.sleep(0.3)))
        conn = wsclient.connect(server.url())
        with self.assertRaises(wsclient.WebSocketError) as e:
            conn.recv(2)
        self.assertIn("too large", str(e.exception))

    def test_only_this_module_opens_a_socket_of_its_own(self):
        for name in sorted(os.listdir(ROOT)):
            if name.endswith(".py") and name != "wsclient.py":
                self.assertNotIn("create_connection(", read(os.path.join(ROOT, name)), name)


if __name__ == "__main__":
    unittest.main()
