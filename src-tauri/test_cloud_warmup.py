import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import httpx
import numpy as np

from whisper_engine import transcriber


class _LocalGroqTransport(httpx.BaseTransport):
    def __init__(self, port, limits):
        self.port = port
        self.transport = httpx.HTTPTransport(limits=limits, trust_env=False)

    def handle_request(self, request):
        request.url = request.url.copy_with(scheme="http", host="127.0.0.1", port=self.port)
        return self.transport.handle_request(request)

    def close(self):
        self.transport.close()


class _LocalGroqServer:
    def __init__(self):
        self.warmup_started = threading.Event()
        self.release_warmup = threading.Event()
        self.requests = []
        state = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                pass

            def do_GET(self):
                state.requests.append(("GET", self.path, self.client_address))
                state.warmup_started.set()
                state.release_warmup.wait(timeout=2)
                self.respond(b'{"data":[]}')

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                state.requests.append(("POST", self.path, self.client_address))
                self.respond(b"synthetic transcript")

            def respond(self, body):
                try:
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except (ConnectionError, OSError):
                    pass

        class Server(ThreadingHTTPServer):
            def handle_error(self, _request, _client_address):
                pass

        self.server = Server(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.worker = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        self.worker.start()

    def close(self):
        self.release_warmup.set()
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=1)


class TestGroqConnectionWarmup(unittest.TestCase):
    def setUp(self):
        transcriber.close_groq_client()
        self.release = threading.Event()
        self.workers = []

    def tearDown(self):
        self.release.set()
        for worker in self.workers:
            if worker is not None:
                worker.join(timeout=3)
                self.assertFalse(worker.is_alive(), "warmup worker did not exit")
        transcriber.close_groq_client()

    def test_repeated_recording_starts_share_one_unfinished_warmup(self):
        started = threading.Event()
        requests = []
        original_client = httpx.Client

        def respond(request):
            requests.append(request)
            started.set()
            self.release.wait(timeout=2)
            return httpx.Response(200, json={"data": []})

        def create_client(**kwargs):
            return original_client(transport=httpx.MockTransport(respond), **kwargs)

        with patch.object(httpx, "Client", side_effect=create_client):
            first = transcriber.prewarm_groq_connection("synthetic-key")
            self.workers.append(first)
            self.assertTrue(started.wait(timeout=1))
            second = transcriber.prewarm_groq_connection("synthetic-key")
            self.assertIs(first, second)
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0].method, "GET")
            self.assertEqual(requests[0].url.path, "/openai/v1/models")
            self.assertEqual(requests[0].headers["Authorization"], "Bearer synthetic-key")
            self.assertEqual(requests[0].content, b"")
            self.assertLessEqual(requests[0].extensions["timeout"]["read"], 2)

    def test_recent_transcription_skips_redundant_connection_probe(self):
        requests = []
        original_client = httpx.Client

        def respond(request):
            requests.append(request)
            return httpx.Response(200, text="synthetic transcript")

        def create_client(**kwargs):
            return original_client(transport=httpx.MockTransport(respond), **kwargs)

        with patch.object(httpx, "Client", side_effect=create_client):
            transcriber.transcribe_cloud(
                np.full(16000, 0.02, dtype=np.float32),
                "it", 1, "synthetic-key", False, lambda _event: None, None,
            )
            warmup = transcriber.prewarm_groq_connection("synthetic-key")
            self.workers.append(warmup)
            self.assertIsNone(warmup)
            self.assertEqual([request.method for request in requests], ["POST"])

    def test_delayed_warmup_cannot_replace_client_selected_by_key_rotation(self):
        checked = threading.Event()
        requests = []
        original_client = httpx.Client

        def cancelled():
            if threading.current_thread() is not threading.main_thread():
                checked.set()
                self.release.wait(timeout=2)
            return False

        def respond(request):
            requests.append(request)
            return httpx.Response(200, json={"data": []})

        def create_client(**kwargs):
            return original_client(transport=httpx.MockTransport(respond), **kwargs)

        with patch.object(httpx, "Client", side_effect=create_client):
            transcriber.get_groq_client("synthetic-old-key")
            warmup = transcriber.prewarm_groq_connection("synthetic-old-key", cancelled)
            self.workers.append(warmup)
            self.assertTrue(checked.wait(timeout=1))
            current = transcriber.get_groq_client("synthetic-new-key")
            self.release.set()
            warmup.join(timeout=1)
            self.assertIs(transcriber.get_groq_client("synthetic-new-key"), current)
            self.assertEqual(requests, [])

    def test_shutdown_invalidates_a_warmup_waiting_to_acquire_its_client(self):
        checked = threading.Event()
        requests = []
        created = []
        original_client = httpx.Client

        def cancelled():
            if threading.current_thread() is not threading.main_thread():
                checked.set()
                self.release.wait(timeout=2)
            return False

        def create_client(**kwargs):
            client = original_client(
                transport=httpx.MockTransport(lambda request: requests.append(request)), **kwargs,
            )
            created.append(client)
            return client

        with patch.object(httpx, "Client", side_effect=create_client):
            warmup = transcriber.prewarm_groq_connection("synthetic-key", cancelled)
            self.workers.append(warmup)
            self.assertTrue(checked.wait(timeout=1))
            transcriber.close_groq_client()
            self.release.set()
            warmup.join(timeout=1)
            self.assertEqual(created, [])
            self.assertEqual(requests, [])

    def test_active_warmup_keeps_rotated_client_open_until_response_completes(self):
        started = threading.Event()
        original_client = httpx.Client

        def respond(request):
            started.set()
            self.release.wait(timeout=2)
            return httpx.Response(200, json={"data": []})

        def create_client(**kwargs):
            return original_client(transport=httpx.MockTransport(respond), **kwargs)

        with patch.object(httpx, "Client", side_effect=create_client):
            previous = transcriber.get_groq_client("synthetic-old-key")
            warmup = transcriber.prewarm_groq_connection("synthetic-old-key")
            self.workers.append(warmup)
            self.assertTrue(started.wait(timeout=1))
            current = transcriber.get_groq_client("synthetic-new-key")
            self.assertFalse(previous.is_closed)
            self.release.set()
            warmup.join(timeout=1)
            self.assertTrue(previous.is_closed)
            self.assertFalse(current.is_closed)
            self.assertIs(transcriber.get_groq_client("synthetic-new-key"), current)

    def test_shutdown_keeps_active_warmup_leased_until_it_finishes(self):
        started = threading.Event()
        original_client = httpx.Client

        def respond(request):
            started.set()
            self.release.wait(timeout=2)
            return httpx.Response(200, json={"data": []})

        def create_client(**kwargs):
            return original_client(transport=httpx.MockTransport(respond), **kwargs)

        with patch.object(httpx, "Client", side_effect=create_client):
            client = transcriber.get_groq_client("synthetic-key")
            warmup = transcriber.prewarm_groq_connection("synthetic-key")
            self.workers.append(warmup)
            self.assertTrue(started.wait(timeout=1))
            transcriber.close_groq_client()
            self.assertFalse(client.is_closed)
            self.release.set()
            warmup.join(timeout=1)
            self.assertTrue(client.is_closed)


class TestGroqWarmupHTTPPool(unittest.TestCase):
    def setUp(self):
        transcriber.close_groq_client()
        self.server = _LocalGroqServer()
        self.workers = []
        original_client = httpx.Client

        def create_client(**kwargs):
            transport = _LocalGroqTransport(self.server.server.server_address[1], kwargs["limits"])
            return original_client(transport=transport, **kwargs)

        self.client_patch = patch.object(httpx, "Client", side_effect=create_client)
        self.client_patch.start()

    def tearDown(self):
        self.server.release_warmup.set()
        for worker in self.workers:
            if worker is not None:
                worker.join(timeout=3)
                self.assertFalse(worker.is_alive(), "request worker did not exit")
        transcriber.close_groq_client()
        self.client_patch.stop()
        self.server.close()

    def test_transcription_finishes_while_warmup_response_is_still_pending(self):
        warmup = transcriber.prewarm_groq_connection("synthetic-key")
        self.workers.append(warmup)
        self.assertTrue(self.server.warmup_started.wait(timeout=1))
        finished = threading.Event()
        events = []

        def transcribe():
            transcriber.transcribe_cloud(
                np.full(16000, 0.02, dtype=np.float32),
                "it", 1, "synthetic-key", False, events.append, None,
            )
            finished.set()

        worker = threading.Thread(target=transcribe, daemon=True)
        self.workers.append(worker)
        worker.start()
        self.assertTrue(finished.wait(timeout=0.5), "warmup occupied the transcription connection")
        self.assertTrue(warmup.is_alive())
        self.assertEqual([event["status"] for event in events], ["result"])
        self.assertEqual([method for method, *_ in self.server.requests], ["GET", "POST"])

    def test_transcription_reuses_warmed_connection_after_ninety_seconds_idle(self):
        self.server.release_warmup.set()
        warmup = transcriber.prewarm_groq_connection("synthetic-key")
        self.workers.append(warmup)
        warmup.join(timeout=2)
        self.assertFalse(warmup.is_alive())
        later = time.monotonic() + 90
        events = []

        with patch("httpcore._sync.http11.time.monotonic", return_value=later):
            transcriber.transcribe_cloud(
                np.full(16000, 0.02, dtype=np.float32),
                "it", 1, "synthetic-key", False, events.append, None,
            )

        self.assertEqual([event["status"] for event in events], ["result"])
        self.assertEqual(len(self.server.requests), 2)
        self.assertEqual(self.server.requests[0][2], self.server.requests[1][2])

    def test_warmup_timeout_is_quiet_and_has_a_retry_cooldown(self):
        warmup = transcriber.prewarm_groq_connection("synthetic-key")
        self.workers.append(warmup)
        self.assertTrue(self.server.warmup_started.wait(timeout=1))
        warmup.join(timeout=2)
        self.assertFalse(warmup.is_alive())
        repeated = transcriber.prewarm_groq_connection("synthetic-key")
        self.workers.append(repeated)
        self.assertIsNone(repeated)
        events = []
        transcriber.transcribe_cloud(
            np.full(16000, 0.02, dtype=np.float32),
            "it", 1, "synthetic-key", False, events.append, None,
        )
        self.assertEqual([event["status"] for event in events], ["result"])
        self.assertEqual([method for method, *_ in self.server.requests].count("POST"), 1)

    def test_cloud_recording_and_stop_do_not_wait_for_connection_probe(self):
        from whisper_engine import engine as engine_module, ipc

        engine = engine_module.WhisperEngine()
        engine.provider = "cloud"
        engine.groq_api_key = "synthetic-key"
        listening = threading.Event()
        completed = threading.Event()
        events = []

        def log(event):
            events.append(event)
            if event["status"] == "listening":
                listening.set()
            elif event["status"] == "result":
                completed.set()

        class InputStream:
            def __init__(self, **kwargs):
                self.callback = kwargs["callback"]

            def __enter__(self):
                self.callback(np.full((512, 1), 0.02, dtype=np.float32), 512, None, None)
                return self

            def __exit__(self, *_args):
                return False

        engine.log = log
        try:
            with patch.object(engine_module.sd, "InputStream", InputStream):
                ipc.handle_command("transcribe", {"provider": "cloud", "language": "it"}, engine)
                self.assertTrue(listening.wait(timeout=1), "microphone capture waited for network")
                self.assertTrue(self.server.warmup_started.wait(timeout=1))
                warmup = transcriber.prewarm_groq_connection("synthetic-key")
                self.workers.append(warmup)
                ipc.handle_command("stop", {}, engine)
                self.assertTrue(completed.wait(timeout=0.8), "stop waited for the connection probe")
                self.assertTrue(warmup.is_alive())
                self.assertEqual([event["status"] for event in events].count("result"), 1)
        finally:
            engine._shutting_down = True
            engine.close_transcription_worker()


if __name__ == "__main__":
    unittest.main()
