"""
Unit tests for WhisperEngine (whisper_engine.py).

Run with:
    python -m pytest test_whisper_engine.py -v
    or
    python -m unittest test_whisper_engine.py -v
"""

import json
import io
import sys
import queue
import unittest
from unittest.mock import patch, MagicMock, PropertyMock
import numpy as np

# Mock heavy external dependencies before importing the module under test.
# This avoids ImportError when faster_whisper / sounddevice are not installed
# in the test environment and also keeps tests fast.
sys.modules["faster_whisper"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()
sys.modules["huggingface_hub"] = MagicMock()

from whisper_engine import WhisperEngine, SAMPLE_RATE, BLOCK_SIZE


class TestWhisperEngineInit(unittest.TestCase):
    """Basic construction checks."""

    def test_initial_state(self):
        engine = WhisperEngine()
        self.assertIsNone(engine.model)
        self.assertIsNone(engine.current_model_size)
        self.assertIsNone(engine.models_dir)
        self.assertFalse(engine.is_recording)
        self.assertIsInstance(engine.audio_queue, queue.Queue)
        self.assertEqual(engine.current_device, "cpu")
        self.assertEqual(engine.compute_device, "cpu")


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
class TestLog(unittest.TestCase):
    """Verify that log() emits well-formed JSON to stdout."""

    def setUp(self):
        self.engine = WhisperEngine()

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_log_outputs_valid_json(self, mock_stdout):
        payload = {"status": "info", "message": "hello"}
        self.engine.log(payload)
        raw = mock_stdout.getvalue().strip()
        parsed = json.loads(raw)
        self.assertEqual(parsed, payload)

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_log_preserves_all_keys(self, mock_stdout):
        payload = {"status": "result", "text": "ciao", "extra": 42}
        self.engine.log(payload)
        parsed = json.loads(mock_stdout.getvalue().strip())
        self.assertIn("status", parsed)
        self.assertIn("text", parsed)
        self.assertIn("extra", parsed)

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_log_flushes_stdout(self, mock_stdout):
        """log() must call sys.stdout.flush() so Tauri reads output immediately."""
        with patch.object(mock_stdout, "flush") as flush_spy:
            self.engine.log({"status": "ready"})
            flush_spy.assert_called_once()


# ---------------------------------------------------------------------------
# JSON command parsing  (the run() loop)
# ---------------------------------------------------------------------------
class TestRunCommandParsing(unittest.TestCase):
    """Feed JSON lines to run() and verify each command is handled."""

    def _make_engine(self):
        engine = WhisperEngine()
        engine.models_dir = "/tmp/models"
        return engine

    # -- init ---------------------------------------------------------------
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_cmd_init_sets_models_dir(self, _):
        engine = self._make_engine()
        lines = [
            json.dumps({"command": "init", "models_dir": "/some/path"}) + "\n",
            json.dumps({"command": "quit"}) + "\n",
        ]
        with patch("sys.stdin", io.StringIO("".join(lines))):
            engine.run()
        self.assertEqual(engine.models_dir, "/some/path")

    # -- download -----------------------------------------------------------
    @patch("whisper_engine.threading.Thread")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_cmd_download_starts_thread(self, _, mock_thread_cls):
        engine = self._make_engine()
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        lines = [
            json.dumps({"command": "download", "model": "small"}) + "\n",
            json.dumps({"command": "quit"}) + "\n",
        ]
        with patch("sys.stdin", io.StringIO("".join(lines))):
            engine.run()

        mock_thread_cls.assert_called_once()
        call_kwargs = mock_thread_cls.call_args
        self.assertEqual(call_kwargs.kwargs.get("target") or call_kwargs[1].get("target", call_kwargs[0][0] if call_kwargs[0] else None),
                         engine.download_model)
        mock_thread.start.assert_called_once()

    # -- transcribe ---------------------------------------------------------
    @patch("whisper_engine.threading.Thread")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_cmd_transcribe_starts_thread(self, _, mock_thread_cls):
        engine = self._make_engine()
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        lines = [
            json.dumps({"command": "transcribe", "device": 1, "model": "base"}) + "\n",
            json.dumps({"command": "quit"}) + "\n",
        ]
        with patch("sys.stdin", io.StringIO("".join(lines))):
            engine.run()

        # At least one Thread was created for transcription
        self.assertTrue(mock_thread.start.called)

    @patch("whisper_engine.threading.Thread")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_cmd_transcribe_defaults_model_to_small(self, _, mock_thread_cls):
        engine = self._make_engine()
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        lines = [
            json.dumps({"command": "transcribe", "device": 0}) + "\n",
            json.dumps({"command": "quit"}) + "\n",
        ]
        with patch("sys.stdin", io.StringIO("".join(lines))):
            engine.run()

        # The thread args should contain the default model "small"
        call_args = mock_thread_cls.call_args
        args_tuple = call_args.kwargs.get("args") or call_args[1].get("args")
        self.assertIn("small", args_tuple)

    # -- stop ---------------------------------------------------------------
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_cmd_stop_sets_is_recording_false(self, _):
        engine = self._make_engine()
        engine.is_recording = True
        lines = [
            json.dumps({"command": "stop"}) + "\n",
            json.dumps({"command": "quit"}) + "\n",
        ]
        with patch("sys.stdin", io.StringIO("".join(lines))):
            engine.run()
        self.assertFalse(engine.is_recording)

    # -- quit ---------------------------------------------------------------
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_cmd_quit_exits_loop(self, mock_stdout):
        engine = self._make_engine()
        lines = [
            json.dumps({"command": "quit"}) + "\n",
            # This line should never be reached:
            json.dumps({"command": "init", "models_dir": "/should/not/happen"}) + "\n",
        ]
        with patch("sys.stdin", io.StringIO("".join(lines))):
            engine.run()
        # models_dir should remain untouched (set in _make_engine, not overwritten)
        self.assertEqual(engine.models_dir, "/tmp/models")

    # -- unknown command (silently ignored) ---------------------------------
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_unknown_command_does_not_crash(self, mock_stdout):
        engine = self._make_engine()
        lines = [
            json.dumps({"command": "nonexistent"}) + "\n",
            json.dumps({"command": "quit"}) + "\n",
        ]
        with patch("sys.stdin", io.StringIO("".join(lines))):
            engine.run()  # should not raise


# ---------------------------------------------------------------------------
# Invalid / malformed JSON
# ---------------------------------------------------------------------------
class TestInvalidJsonHandling(unittest.TestCase):
    """run() must survive bad input without crashing."""

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_malformed_json_logs_error(self, mock_stdout):
        engine = WhisperEngine()
        lines = [
            "this is not json\n",
            json.dumps({"command": "quit"}) + "\n",
        ]
        with patch("sys.stdin", io.StringIO("".join(lines))):
            engine.run()

        # The engine should have logged an error for the bad line
        output_lines = mock_stdout.getvalue().strip().split("\n")
        error_found = False
        for line in output_lines:
            parsed = json.loads(line)
            if parsed.get("status") == "error":
                error_found = True
                break
        self.assertTrue(error_found, "Expected an error log for malformed JSON")

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_empty_json_object_does_not_crash(self, mock_stdout):
        engine = WhisperEngine()
        lines = [
            json.dumps({}) + "\n",
            json.dumps({"command": "quit"}) + "\n",
        ]
        with patch("sys.stdin", io.StringIO("".join(lines))):
            engine.run()  # command is None, no branch matches, no error

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_partial_json_logs_error(self, mock_stdout):
        engine = WhisperEngine()
        lines = [
            '{"command": "init"\n',  # missing closing brace
            json.dumps({"command": "quit"}) + "\n",
        ]
        with patch("sys.stdin", io.StringIO("".join(lines))):
            engine.run()

        output_lines = mock_stdout.getvalue().strip().split("\n")
        statuses = [json.loads(l).get("status") for l in output_lines]
        self.assertIn("error", statuses)


# ---------------------------------------------------------------------------
# audio_callback  --  volume calculation
# ---------------------------------------------------------------------------
class TestAudioCallback(unittest.TestCase):
    """Verify audio_callback enqueues data and computes volume."""

    def setUp(self):
        self.engine = WhisperEngine()
        self.engine.is_recording = True
        # Reset throttle timer so the volume log fires immediately
        self.engine._last_vol_time = 0

    def test_data_enqueued(self):
        """audio_callback must put a copy of indata into audio_queue."""
        indata = np.zeros((BLOCK_SIZE, 1), dtype=np.float32)
        self.engine.audio_callback(indata, BLOCK_SIZE, None, None)
        self.assertFalse(self.engine.audio_queue.empty())

    def test_enqueued_data_is_copy(self):
        """Enqueued array must be independent of the original buffer."""
        indata = np.ones((BLOCK_SIZE, 1), dtype=np.float32)
        self.engine.audio_callback(indata, BLOCK_SIZE, None, None)
        queued = self.engine.audio_queue.get_nowait()
        # Mutate original -- queued data should be unaffected
        indata[:] = 999
        self.assertTrue(np.all(queued == 1.0))

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_volume_level_for_silence(self, mock_stdout):
        """Silence (all zeros) should yield volume 0."""
        indata = np.zeros((BLOCK_SIZE, 1), dtype=np.float32)
        self.engine.audio_callback(indata, BLOCK_SIZE, None, None)
        raw = mock_stdout.getvalue().strip()
        if raw:  # volume may be logged
            parsed = json.loads(raw)
            self.assertEqual(parsed["value"], 0)

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_volume_level_capped_at_100(self, mock_stdout):
        """Extremely loud input should not produce a level above 100."""
        indata = np.full((BLOCK_SIZE, 1), 100.0, dtype=np.float32)
        self.engine.audio_callback(indata, BLOCK_SIZE, None, None)
        raw = mock_stdout.getvalue().strip()
        if raw:
            parsed = json.loads(raw)
            self.assertLessEqual(parsed["value"], 100)

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_volume_not_logged_when_not_recording(self, mock_stdout):
        """When is_recording is False, no volume log should appear."""
        self.engine.is_recording = False
        indata = np.ones((BLOCK_SIZE, 1), dtype=np.float32)
        self.engine.audio_callback(indata, BLOCK_SIZE, None, None)
        raw = mock_stdout.getvalue().strip()
        # Nothing volume-related should be printed
        if raw:
            for line in raw.split("\n"):
                parsed = json.loads(line)
                self.assertNotEqual(parsed.get("status"), "volume")

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_status_warning_on_sd_status(self, mock_stdout):
        """If sounddevice reports a status, it should be logged as a warning."""
        indata = np.zeros((BLOCK_SIZE, 1), dtype=np.float32)
        self.engine.audio_callback(indata, BLOCK_SIZE, None, "input overflow")
        output_lines = mock_stdout.getvalue().strip().split("\n")
        warning_found = any(
            json.loads(l).get("status") == "warning" for l in output_lines if l
        )
        self.assertTrue(warning_found)


# ---------------------------------------------------------------------------
# Model path construction
# ---------------------------------------------------------------------------
class TestModelPath(unittest.TestCase):

    def test_download_model_path(self):
        """download_model should build the local_dir as models_dir/faster-whisper-{size}."""
        import os
        engine = WhisperEngine()
        engine.models_dir = "/home/user/.traflix/models"

        with patch("whisper_engine.snapshot_download") as mock_dl, \
             patch.object(engine, "verify_model", return_value=(True, "ok")), \
             patch("sys.stdout", new_callable=io.StringIO):
            engine.download_model("small")

        expected_local_dir = os.path.join("/home/user/.traflix/models", "faster-whisper-small")
        mock_dl.assert_called_once()
        call_kwargs = mock_dl.call_args
        self.assertEqual(
            call_kwargs.kwargs.get("local_dir") or call_kwargs[1].get("local_dir"),
            expected_local_dir,
        )

    def test_load_model_path(self):
        """load_model should pass models_dir/faster-whisper-{size} to WhisperModel."""
        import os
        engine = WhisperEngine()
        engine.models_dir = "/models"

        with patch("whisper_engine.WhisperModel") as MockModel, \
             patch.object(engine, "verify_model", return_value=(True, "ok")), \
             patch("sys.stdout", new_callable=io.StringIO):
            engine.load_model("large-v2")

        expected_root = os.path.join("/models", "faster-whisper-large-v2")
        MockModel.assert_called_once_with(expected_root, device="cpu", compute_type="int8")

    def test_load_model_caches(self):
        """Calling load_model twice with the same size must NOT reload."""
        engine = WhisperEngine()
        engine.models_dir = "/models"

        with patch("whisper_engine.WhisperModel") as MockModel, \
             patch.object(engine, "verify_model", return_value=(True, "ok")), \
             patch("sys.stdout", new_callable=io.StringIO):
            engine.load_model("small")
            engine.load_model("small")

        MockModel.assert_called_once()

    def test_load_model_reloads_on_size_change(self):
        """Switching model size should trigger a new WhisperModel load."""
        engine = WhisperEngine()
        engine.models_dir = "/models"

        with patch("whisper_engine.WhisperModel") as MockModel, \
             patch.object(engine, "verify_model", return_value=(True, "ok")), \
             patch("sys.stdout", new_callable=io.StringIO):
            engine.load_model("small")
            engine.load_model("medium")

        self.assertEqual(MockModel.call_count, 2)


# ---------------------------------------------------------------------------
# Transcription flow (mocked model)
# ---------------------------------------------------------------------------
class TestTranscriptionFlow(unittest.TestCase):
    """Test the transcribe() method with a mocked Whisper model and InputStream."""

    def _setup_engine(self):
        engine = WhisperEngine()
        engine.models_dir = "/models"
        engine.model = MagicMock()
        engine.current_model_size = "small"
        engine.current_device = "cpu"
        return engine

    def _mock_input_stream(self, engine, audio_blocks=None):
        """Helper to mock sd.InputStream context manager.
        transcribe() resets audio_queue then enters the `with` block.
        We put blocks into the queue AND use a sentinel approach:
        after the blocks, we schedule is_recording=False via a
        queue callback so the while-loop reads all blocks first."""
        import sounddevice as sd
        import threading

        def fake_enter(self_inner):
            if audio_blocks:
                for block in audio_blocks:
                    engine.audio_queue.put(block.copy())
                # Let the while-loop drain the queue before stopping
                def stop_later():
                    import time; time.sleep(0.15)
                    engine.is_recording = False
                threading.Thread(target=stop_later, daemon=True).start()
            else:
                engine.is_recording = False
            return MagicMock()
        sd.InputStream.return_value.__enter__ = fake_enter
        sd.InputStream.return_value.__exit__ = MagicMock(return_value=False)

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_transcribe_returns_result(self, mock_stdout):
        engine = self._setup_engine()
        fake_audio = np.random.randn(BLOCK_SIZE, 1).astype(np.float32)

        mock_segment = MagicMock()
        mock_segment.text = "ciao mondo"
        mock_info = MagicMock()
        engine.model.transcribe.return_value = ([mock_segment], mock_info)

        self._mock_input_stream(engine, [fake_audio])

        with patch.object(engine, "load_model"):
            engine.transcribe(0, "small")

        output_lines = mock_stdout.getvalue().strip().split("\n")
        parsed_lines = [json.loads(l) for l in output_lines if l]
        result_logs = [p for p in parsed_lines if p.get("status") == "result"]
        self.assertEqual(len(result_logs), 1)
        self.assertEqual(result_logs[0]["text"], "ciao mondo")
        self.assertIn("duration", result_logs[0])

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_transcribe_no_audio_logs_ready(self, mock_stdout):
        """If no audio is captured the engine should log a message, not crash."""
        engine = self._setup_engine()
        self._mock_input_stream(engine, [])

        with patch.object(engine, "load_model"):
            engine.transcribe(0, "small")

        output_lines = mock_stdout.getvalue().strip().split("\n")
        parsed_lines = [json.loads(l) for l in output_lines if l]
        ready_or_info = [p for p in parsed_lines if p.get("status") == "ready"]
        self.assertTrue(len(ready_or_info) >= 1, "Expected a 'ready' log when no audio captured")

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_transcribe_concatenates_multiple_blocks(self, mock_stdout):
        """Multiple audio blocks should be concatenated before transcription."""
        engine = self._setup_engine()

        block1 = np.ones((BLOCK_SIZE, 1), dtype=np.float32)
        block2 = np.ones((BLOCK_SIZE, 1), dtype=np.float32) * 0.5

        mock_segment = MagicMock()
        mock_segment.text = "test"
        engine.model.transcribe.return_value = ([mock_segment], MagicMock())

        self._mock_input_stream(engine, [block1, block2])

        with patch.object(engine, "load_model"):
            engine.transcribe(0, "small")

        call_args = engine.model.transcribe.call_args
        self.assertIsNotNone(call_args, "model.transcribe should have been called")
        recording = call_args[0][0]
        expected_len = BLOCK_SIZE * 2
        self.assertEqual(len(recording), expected_len)

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_transcribe_error_logged(self, mock_stdout):
        """If the model raises, the error should be logged as JSON."""
        engine = self._setup_engine()
        engine.model.transcribe.side_effect = RuntimeError("model exploded")

        fake_audio = np.zeros((BLOCK_SIZE, 1), dtype=np.float32)
        self._mock_input_stream(engine, [fake_audio])

        with patch.object(engine, "load_model"):
            engine.transcribe(0, "small")

        output_lines = mock_stdout.getvalue().strip().split("\n")
        parsed_lines = [json.loads(l) for l in output_lines if l]
        error_logs = [p for p in parsed_lines if p.get("status") == "error"]
        self.assertTrue(len(error_logs) >= 1)
        self.assertIn("model exploded", error_logs[0]["message"])


# ---------------------------------------------------------------------------
# Download model error handling
# ---------------------------------------------------------------------------
class TestDownloadModel(unittest.TestCase):

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_download_error_logged(self, mock_stdout):
        """If snapshot_download raises, the error is logged as JSON."""
        engine = WhisperEngine()
        engine.models_dir = "/models"

        with patch("whisper_engine.snapshot_download", side_effect=OSError("disk full")):
            engine.download_model("tiny")

        output_lines = mock_stdout.getvalue().strip().split("\n")
        parsed = [json.loads(l) for l in output_lines if l]
        error_logs = [p for p in parsed if p.get("status") == "error"]
        self.assertTrue(len(error_logs) >= 1)
        self.assertIn("disk full", error_logs[0]["message"])

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_download_success_logs_complete(self, mock_stdout):
        engine = WhisperEngine()
        engine.models_dir = "/models"

        with patch("whisper_engine.snapshot_download"), \
             patch.object(engine, "verify_model", return_value=(True, "ok")):
            engine.download_model("small")

        output_lines = mock_stdout.getvalue().strip().split("\n")
        parsed = [json.loads(l) for l in output_lines if l]
        statuses = [p["status"] for p in parsed]
        self.assertIn("downloading", statuses)
        self.assertIn("download_complete", statuses)


# ---------------------------------------------------------------------------
# Constants sanity check
# ---------------------------------------------------------------------------
class TestConstants(unittest.TestCase):

    def test_sample_rate(self):
        self.assertEqual(SAMPLE_RATE, 16000)

    def test_block_size(self):
        self.assertEqual(BLOCK_SIZE, 4000)


if __name__ == "__main__":
    unittest.main()
