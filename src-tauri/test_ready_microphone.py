import concurrent.futures
import queue
import threading
import unittest
import sys
from unittest.mock import Mock, MagicMock
import numpy as np
sys.modules.setdefault("sounddevice", MagicMock())
from whisper_engine.ready_microphone import ReadyMicrophone, PRE_ROLL_SAMPLES
from whisper_engine.engine import WhisperEngine, _RecordingSession


class FakeStream:
    def __init__(self, **options):
        self.options = options
        self.closed = False
    def start(self):
        pass
    def stop(self):
        self.options["finished_callback"]()
    def close(self):
        self.closed = True
    def push(self, data):
        data = np.array(data, dtype=np.float32).reshape(-1, 1)
        self.options["callback"](data, data.size, None, None)


class ReadyMicrophoneTests(unittest.TestCase):
    def setUp(self):
        self.streams = []
        def factory(**options):
            stream = FakeStream(**options)
            self.streams.append(stream)
            return stream
        self.mic = ReadyMicrophone(factory)
        self.addCleanup(self.mic.close)
        self.mic.prepare(True, None)

    def test_idle_buffer_is_bounded_and_exact(self):
        source = np.arange(PRE_ROLL_SAMPLES * 3, dtype=np.float32)
        self.streams[0].push(source)
        self.assertEqual(self.mic.samples, PRE_ROLL_SAMPLES)
        self.assertLessEqual(sum(x.nbytes for x in self.mic.ring), PRE_ROLL_SAMPLES * 4)
        session = _RecordingSession()
        with self.mic.capture(None, session, Mock()):
            np.testing.assert_array_equal(session.queue.get_nowait(), source[-PRE_ROLL_SAMPLES:])
        self.assertEqual(self.mic.samples, 0)

    def test_active_audio_and_late_callback_never_replay_in_next_clip(self):
        first = _RecordingSession()
        callback = Mock()
        with self.mic.capture(None, first, callback):
            self.streams[0].push([1, 2])
            first.stop(drain_seconds=0)
            self.streams[0].push([3])
        callback.assert_called_once()
        self.streams[0].push([4])
        second = _RecordingSession()
        with self.mic.capture(None, second, Mock()):
            np.testing.assert_array_equal(second.queue.get_nowait(), [4])
            self.assertTrue(second.queue.empty())
        self.assertEqual(len(self.streams), 1)

    def test_device_switch_and_old_callbacks_are_fenced(self):
        old = self.streams[0]
        self.mic.prepare(True, "other")
        self.assertTrue(old.closed)
        old.push([99])
        old.options["finished_callback"]()
        self.assertTrue(self.mic.healthy)
        self.assertEqual(self.mic.samples, 0)
        self.streams[-1].push([7])
        self.assertEqual(self.mic.samples, 1)
        self.mic.prepare(False, "other")
        self.assertTrue(self.streams[-1].closed)
        self.assertEqual(self.mic.samples, 0)

    def test_configuration_is_deferred_until_active_clip_ends(self):
        with self.mic.capture(None, _RecordingSession(), Mock()):
            self.mic.prepare(False, "changed")
            self.assertFalse(self.streams[0].closed)
        self.mic.prepare(False, "changed")
        self.assertTrue(self.streams[0].closed)

    def test_device_failure_wakes_capture_and_reconnects(self):
        session = _RecordingSession()
        with self.assertRaisesRegex(RuntimeError, "disconnesso"):
            with self.mic.capture(None, session, Mock()):
                self.streams[0].options["finished_callback"]()
                self.assertIsNone(session.queue.get(timeout=1))
        self.mic.prepare(True, None)
        self.assertEqual(len(self.streams), 2)
        self.assertTrue(self.mic.healthy)

    def test_both_providers_reuse_one_stream_and_preserve_session_audio(self):
        engine = WhisperEngine()
        engine.keep_ready = True
        engine._microphone = self.mic
        engine.load_model = Mock(return_value=object())
        listening = threading.Event()
        processed = threading.Event()
        recordings = []
        engine.log = lambda e: listening.set() if e.get("status") == "listening" else None
        def process(audio, model, language, duration, provider, **options):
            recordings.append((audio.copy(), duration, provider))
            processed.set()
        engine._process_recording = process
        try:
            for provider in ("cloud", "local"):
                engine.provider = provider
                listening.clear()
                processed.clear()
                self.streams[-1].push(np.full(512, 0.05))
                # Direct capture invocation avoids cloud network preparation.
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as worker:
                    future = worker.submit(engine.transcribe, None, "parakeet", "it")
                    self.assertTrue(listening.wait(2))
                    self.streams[-1].push(np.full(1024, -0.1))
                    engine.stop_recording()
                    future.result(timeout=3)
                self.assertTrue(processed.wait(1))
                audio, duration, result_provider = recordings[-1]
                self.assertEqual(result_provider, provider)
                self.assertEqual(audio.size, 1536)
                self.assertEqual(duration, 1536 / 16000)
                self.assertTrue((audio[:512] > 0).all())
                self.assertTrue((audio[512:] < 0).all())
            self.assertEqual(len(self.streams), 1)
        finally:
            engine._shutting_down = True
            engine.close_transcription_worker()

    def test_cold_model_load_preserves_audio_and_stop_signal(self):
        engine = WhisperEngine()
        engine.keep_ready = True
        engine._microphone = self.mic
        started, release, listening, processing = (threading.Event() for _ in range(4))
        events = []
        def log(event):
            events.append(event)
            if event["status"] == "listening": listening.set()
            if event["status"] == "processing": processing.set()
        def load(_):
            started.set()
            self.assertTrue(release.wait(2))
            return object()
        engine.log = log
        engine.load_model = load
        engine._process_recording = Mock()
        try:
            self.streams[0].push(np.full(512, 0.05))
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as worker:
                future = worker.submit(engine.transcribe, None, "parakeet", "it")
                self.assertTrue(started.wait(2))
                self.assertTrue(listening.is_set())
                self.streams[0].push(np.full(512, 0.1))
                engine.stop_recording()
                self.assertTrue(processing.wait(1))
                release.set()
                future.result(timeout=3)
            self.assertEqual(engine._process_recording.call_args.args[0].size, 1024)
            self.assertEqual(sum(e["status"] == "processing" for e in events), 1)
        finally:
            release.set()
            engine._shutting_down = True
            engine.close_transcription_worker()

    def test_ipc_can_disable_keep_ready_and_change_device(self):
        from whisper_engine.ipc import handle_command
        engine = Mock()
        handle_command("configure_microphone", {"enabled": False, "device": "microphone"}, engine)
        engine.configure_microphone.assert_called_once_with(False, "microphone")

    def test_stop_while_opening_does_not_load_a_cold_model(self):
        engine = WhisperEngine()
        engine.keep_ready = True
        engine.load_model = Mock()
        events = []
        engine.log = events.append
        class StoppedStream(FakeStream):
            def start(self):
                engine.stop_recording()
        engine._microphone = ReadyMicrophone(StoppedStream)
        try:
            engine.transcribe(None, "parakeet")
            engine.load_model.assert_not_called()
            self.assertNotIn("listening", [e["status"] for e in events])
            self.assertNotIn("processing", [e["status"] for e in events])
        finally:
            engine.close_transcription_worker()
