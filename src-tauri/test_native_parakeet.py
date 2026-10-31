"""Lifecycle and binary framing guards for the native local backend."""
import io
import json
import queue
import unittest
from unittest.mock import Mock, patch
import numpy as np
from whisper_engine import native_parakeet as native, model, parakeet


class NativeBackendTests(unittest.TestCase):
    def session(self, reply):
        session = native.NativeSession.__new__(native.NativeSession)
        session.process = Mock()
        session.process.stdin = io.BytesIO()
        session.replies = queue.Queue()
        session.replies.put(reply)
        return session

    def test_binary_frame_preserves_samples_without_json_audio(self):
        session = self.session({"status": "result", "text": "Ciao."})
        audio = np.array([0.125, -0.5], dtype="<f4")
        process = session.process
        self.assertEqual(session._exchange({"command": "transcribe", "samples": 2}, audio)["text"], "Ciao.")
        header, binary = process.stdin.getvalue().split(b"\n", 1)
        self.assertEqual(json.loads(header)["samples"], 2)
        self.assertEqual(binary, audio.tobytes())
        session.process = None

    def test_dead_helper_and_error_replies_release_process(self):
        for reply in [None, {"status": "error", "message": "decoder failed"}, {"status": "ready"}]:
            with self.subTest(reply=reply):
                session = self.session(reply)
                with patch.object(session, "close") as close:
                    with self.assertRaises(RuntimeError):
                        session._exchange({"command": "transcribe", "samples": 1})
                    close.assert_called_once()
                session.process = None

    def test_unload_keeps_active_snapshot_alive(self):
        session = Mock()
        session.transcribe.return_value = "Una prova."
        recognizer = native.NativeRecognizer(session)
        pinned = model.retain_model(recognizer)
        recognizer.close()
        self.assertEqual(pinned.transcribe(np.zeros(24_000, dtype=np.float32))[0].text, "Una prova.")
        pinned.close()

    def test_legacy_install_migrates_to_pinned_gguf(self):
        with patch.object(native, "helper_path", return_value="helper"), \
             patch.object(native, "verify", return_value=False), \
             patch.object(native, "download") as download, \
             patch.object(native, "load", return_value="native") as load, \
             patch.object(parakeet.os.path, "isfile", return_value=True):
            events = []
            self.assertEqual(parakeet.load("models", events.append), "native")
            download.assert_called_once()
            load.assert_called_once()
            self.assertIn("download_complete", [event["status"] for event in events])

    def test_checksum_failure_never_loads_helper(self):
        with patch.object(native, "verify", return_value=False), \
             patch.object(native, "NativeSession") as session:
            with self.assertRaises(RuntimeError):
                native.load("missing", lambda _: None)
            session.assert_not_called()

    def test_download_pins_model_revision(self):
        with patch.object(native, "hf_hub_download") as download, patch.object(native, "verify", return_value=True):
            native.download("models")
            self.assertEqual(download.call_args.kwargs["revision"], native.REVISION)

    def test_loaded_backend_is_reported_to_frontend(self):
        session = Mock()
        session.metadata = {"backend": "vulkan", "device": "Test GPU"}
        with patch.object(native, "verify", return_value=True), patch.object(native, "NativeSession", return_value=session):
            events = []
            recognizer = native.load("models", events.append)
            info = next(event for event in events if event["status"] == "gpu_info")
            self.assertEqual(info["current_device"], "vulkan")
            self.assertIn("Test GPU", info["message"])
            recognizer.close()
