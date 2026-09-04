"""
Unit tests for WhisperEngine (refactored package).

Run with:
    python -m pytest test_whisper_engine.py -v
    or
    python -m unittest test_whisper_engine.py -v
"""

import json
import io
import os
import sys
import queue
import threading
import concurrent.futures
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock, PropertyMock
import numpy as np

# Mock heavy external dependencies before importing the module under test.
# This avoids ImportError when faster_whisper / sounddevice are not installed
# in the test environment and also keeps tests fast.
sys.modules["faster_whisper"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()
sys.modules["huggingface_hub"] = MagicMock()
sys.modules["pywhispercpp"] = MagicMock()
sys.modules["pywhispercpp.model"] = MagicMock()

from whisper_engine.engine import WhisperEngine, _RecordingSession
from whisper_engine.constants import SAMPLE_RATE, BLOCK_SIZE
from whisper_engine.audio import (
    VOLUME_UPDATE_SAMPLES,
    audio_callback as _ac,
    calculate_volume,
    reset_volume_state,
)
from whisper_engine.transcriber import (
    encode_cloud_multipart,
    encode_cloud_multipart_from_recording,
    encode_wav,
)
from whisper_engine import groq_tracker, ipc as ipc_module, transcriber as transcriber_module


class TestIpcSerialization(unittest.TestCase):
    def test_non_volume_events_use_compact_json(self):
        output = io.StringIO()
        with patch.object(sys, "stdout", output):
            ipc_module.log({"status": "ready", "message": "Pronto"})

        self.assertEqual(output.getvalue(), '{"status":"ready","message":"Pronto"}\n')

    def test_recording_status_lines_use_fixed_fast_path(self):
        output = io.StringIO()
        with patch.object(sys, "stdout", output):
            ipc_module.log({"status": "processing", "message": "Trascrizione in corso..."})

        self.assertEqual(
            output.getvalue(),
            '{"status":"processing","message":"Trascrizione in corso..."}\n',
        )


class TestWhisperEngineInit(unittest.TestCase):
    """Basic construction checks."""

    def test_initial_state(self):
        engine = WhisperEngine()
        self.assertIsNone(engine.model)
        self.assertIsNone(engine.current_model_size)
        self.assertIsNone(engine.models_dir)
        self.assertFalse(engine.is_recording)
        self.assertIsInstance(engine.audio_queue, queue.SimpleQueue)
        self.assertEqual(engine.current_device, "cpu")
        self.assertEqual(engine.compute_device, "cpu")

    def test_transcription_worker_reuses_one_warm_thread(self):
        engine = WhisperEngine()
        worker_ids = []
        engine.prepare_transcription_worker()
        try:
            with patch.object(
                engine,
                "transcribe",
                side_effect=lambda *_args: worker_ids.append(threading.get_ident()),
            ):
                first = engine.start_transcription(None, "small")
                second = engine.start_transcription(None, "small")
                first.result(timeout=1)
                second.result(timeout=1)
        finally:
            engine.close_transcription_worker()

        self.assertEqual(len(worker_ids), 2)
        self.assertEqual(worker_ids[0], worker_ids[1])


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
    def test_log_uses_fast_path_for_integer_volume(self, mock_stdout):
        self.engine.log({"status": "volume", "value": 42})
        self.assertEqual(
            mock_stdout.getvalue(),
            '{"status":"volume","value":42}\n',
        )

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_log_keeps_generic_serializer_for_non_integer_volume(self, mock_stdout):
        payload = {"status": "volume", "value": 42.5}
        self.engine.log(payload)
        self.assertEqual(json.loads(mock_stdout.getvalue()), payload)

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_log_keeps_complete_lines_from_concurrent_volume_callbacks(self, mock_stdout):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(self.engine.log, {"status": "volume", "value": value})
                for value in range(200)
            ]
            for future in futures:
                future.result()

        lines = [line for line in mock_stdout.getvalue().splitlines() if line]
        self.assertEqual(len(lines), 200)
        self.assertTrue(all(json.loads(line)["status"] == "volume" for line in lines))

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
    @patch("whisper_engine.ipc.threading.Thread")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_cmd_download_starts_thread(self, _, mock_thread_cls):
        engine = self._make_engine()
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        lines = [
            json.dumps({"command": "download", "model": "small"}) + "\n",
            json.dumps({"command": "quit"}) + "\n",
        ]
        with (
            patch("sys.stdin", io.StringIO("".join(lines))),
            patch.object(engine, "prepare_transcription_worker"),
        ):
            engine.run()

        mock_thread_cls.assert_called_once()
        mock_thread.start.assert_called_once()

    # -- transcribe ---------------------------------------------------------
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_cmd_transcribe_dispatches_to_warm_worker(self, _):
        engine = self._make_engine()

        lines = [
            json.dumps({"command": "transcribe", "device": 1, "model": "base"}) + "\n",
            json.dumps({"command": "quit"}) + "\n",
        ]
        with (
            patch("sys.stdin", io.StringIO("".join(lines))),
            patch.object(engine, "start_transcription") as start_transcription,
        ):
            engine.run()

        start_transcription.assert_called_once_with(1, "base", "it")

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_cmd_transcribe_defaults_model_to_small(self, _):
        engine = self._make_engine()

        lines = [
            json.dumps({"command": "transcribe", "device": 0}) + "\n",
            json.dumps({"command": "quit"}) + "\n",
        ]
        with (
            patch("sys.stdin", io.StringIO("".join(lines))),
            patch.object(engine, "start_transcription") as start_transcription,
        ):
            engine.run()

        start_transcription.assert_called_once_with(0, "small", "it")

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
        self.assertIsNone(engine.audio_queue.get_nowait())

    # -- quit ---------------------------------------------------------------
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_cmd_quit_exits_loop(self, mock_stdout):
        engine = self._make_engine()
        lines = [
            json.dumps({"command": "quit"}) + "\n",
            json.dumps({"command": "init", "models_dir": "/should/not/happen"}) + "\n",
        ]
        with patch("sys.stdin", io.StringIO("".join(lines))):
            engine.run()
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
            engine.run()


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
            engine.run()

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_partial_json_logs_error(self, mock_stdout):
        engine = WhisperEngine()
        lines = [
            '{"command": "init"\n',
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
        reset_volume_state()

    def test_data_enqueued(self):
        """audio_callback must put a copy of indata into audio_queue."""
        indata = np.zeros((BLOCK_SIZE, 1), dtype=np.float32)
        self.engine.audio_callback(indata, BLOCK_SIZE, None, None)
        self.assertFalse(self.engine.audio_queue.empty())
        self.assertEqual(self.engine.audio_queue.get_nowait().ndim, 1)

    def test_enqueued_data_is_copy(self):
        """Enqueued array must be independent of the original buffer."""
        indata = np.ones((BLOCK_SIZE, 1), dtype=np.float32)
        self.engine.audio_callback(indata, BLOCK_SIZE, None, None)
        queued = self.engine.audio_queue.get_nowait()
        indata[:] = 999
        self.assertTrue(np.all(queued == 1.0))

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_volume_level_for_silence(self, mock_stdout):
        """Silence (all zeros) should yield volume 0."""
        indata = np.zeros((BLOCK_SIZE, 1), dtype=np.float32)
        self.engine.audio_callback(indata, BLOCK_SIZE, None, None)
        raw = mock_stdout.getvalue().strip()
        if raw:
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
    def test_duplicate_volume_levels_are_not_emitted(self, mock_stdout):
        indata = np.zeros((BLOCK_SIZE, 1), dtype=np.float32)
        self.engine.audio_callback(indata, BLOCK_SIZE, None, None)
        _ac._volume_sample_count = VOLUME_UPDATE_SAMPLES
        self.engine.audio_callback(indata, BLOCK_SIZE, None, None)

        lines = [line for line in mock_stdout.getvalue().splitlines() if line]
        self.assertEqual(len(lines), 1)

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_volume_not_logged_when_not_recording(self, mock_stdout):
        """When is_recording is False, no volume log should appear."""
        self.engine.is_recording = False
        indata = np.ones((BLOCK_SIZE, 1), dtype=np.float32)
        self.engine.audio_callback(indata, BLOCK_SIZE, None, None)
        self.assertTrue(self.engine.audio_queue.empty())
        raw = mock_stdout.getvalue().strip()
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

    @patch("sys.stdout", new_callable=io.StringIO)
    @patch("whisper_engine.audio.calculate_volume", return_value=42)
    def test_volume_reuses_queued_mono_copy(self, mock_volume, _mock_stdout):
        indata = np.ones((BLOCK_SIZE, 1), dtype=np.float32)
        self.engine.audio_callback(indata, BLOCK_SIZE, None, None)

        volume_input = mock_volume.call_args.args[0]
        self.assertEqual(volume_input.ndim, 1)
        self.assertIsNot(volume_input, indata)

    def test_volume_work_buffer_preserves_calibrated_level(self):
        samples = np.array([0.01, -0.03, 0.05, -0.02], dtype=np.float32)
        rms = float(np.sqrt(np.mean(np.square(samples))))
        peak = float(np.max(np.abs(samples)))
        effective_level = max(rms, peak * 0.08)
        level_db = 20.0 * np.log10(max(effective_level, 1e-6))
        expected = int(
            np.clip(
                (level_db + 58.0) / 46.0 * 100.0,
                0.0,
                100.0,
            )
        )

        self.assertEqual(calculate_volume(samples), expected)

    def test_volume_sanitizes_nonfinite_samples(self):
        samples = np.array([np.nan, np.inf, -np.inf, 0.0], dtype=np.float32)
        self.assertEqual(calculate_volume(samples), 0)


class TestCloudWavEncoding(unittest.TestCase):
    def test_normalized_fast_path_matches_safe_path(self):
        recording = np.linspace(
            -0.75,
            0.75,
            SAMPLE_RATE * 2,
            dtype=np.float32,
        )

        safe_payload = encode_wav(recording).getvalue()
        fast_payload = encode_wav(recording, assume_normalized=True).getvalue()

        self.assertEqual(fast_payload, safe_payload)

    def test_direct_cloud_multipart_matches_legacy_buffer_path(self):
        recording = np.linspace(
            -0.5,
            0.5,
            SAMPLE_RATE * 2,
            dtype=np.float32,
        )

        legacy_payload = encode_cloud_multipart(encode_wav(recording), "it")
        direct_payload = encode_cloud_multipart_from_recording(
            recording,
            "it",
            assume_normalized=True,
        )

        self.assertEqual(direct_payload, legacy_payload)


class TestGroqUsageTracker(unittest.TestCase):
    def test_hourly_usage_resets_when_sidecar_crosses_hour(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            models_dir = os.path.join(temp_dir, "models")
            usage_path = groq_tracker.get_groq_usage_path(models_dir)
            first_now = time.time()

            with patch.object(groq_tracker.pytime, "time", return_value=first_now):
                groq_tracker.record_groq_usage(models_dir, duration_seconds=12.0)

            with open(usage_path, "r") as usage_file:
                first_usage = json.load(usage_file)
            self.assertEqual(first_usage["audio_seconds_hourly"], 12.0)

            with patch.object(
                groq_tracker.pytime,
                "time",
                return_value=first_now + 3600,
            ):
                groq_tracker.record_groq_usage(models_dir, duration_seconds=3.0)

            with open(usage_path, "r") as usage_file:
                second_usage = json.load(usage_file)
            self.assertEqual(second_usage["audio_seconds"], 15.0)
            self.assertEqual(second_usage["audio_seconds_hourly"], 3.0)

    def test_tracker_cache_skips_reloading_same_usage_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            models_dir = os.path.join(temp_dir, "models")
            groq_tracker.record_groq_usage(models_dir, duration_seconds=1.0)

            with patch.object(
                groq_tracker.os.path,
                "exists",
                side_effect=AssertionError("warm cache should skip disk read"),
            ):
                groq_tracker.record_groq_usage(models_dir, duration_seconds=2.0)

            usage_path = groq_tracker.get_groq_usage_path(models_dir)
            with open(usage_path, "r") as usage_file:
                usage = json.load(usage_file)
            self.assertEqual(usage["audio_seconds"], 3.0)

    def test_tracker_noop_does_not_create_usage_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            models_dir = os.path.join(temp_dir, "models")
            groq_tracker.record_groq_usage(models_dir)
            self.assertFalse(os.path.exists(groq_tracker.get_groq_usage_path(models_dir)))

    def test_tracker_error_before_temp_file_creation_is_swallowed(self):
        with patch.object(
            groq_tracker.os.path,
            "exists",
            side_effect=OSError("unavailable"),
        ):
            groq_tracker.record_groq_usage("C:\\unavailable\\models")


class TestCloudTranscription(unittest.TestCase):
    def _recording(self):
        return np.full(SAMPLE_RATE, 0.03, dtype=np.float32)

    def test_success_closes_http_response_after_logging_result(self):
        response = MagicMock(status_code=200, content=b"ciao mondo\n")
        client = MagicMock(headers={"Authorization": "Bearer test"})
        client.send.return_value = response
        events = []

        with patch.object(
            transcriber_module,
            "acquire_groq_client",
            return_value=client,
        ):
            transcriber_module.transcribe_cloud(
                self._recording(), "it", 1.0, "test-key", False,
                events.append, None,
            )

        self.assertEqual([event["status"] for event in events], ["result"])
        response.close.assert_called_once()

    def test_single_channel_matrix_is_normalized_for_cloud(self):
        response = MagicMock(status_code=200, content=b"ok")
        client = MagicMock(headers={"Authorization": "Bearer test"})
        client.send.return_value = response
        events = []

        with patch.object(transcriber_module, "acquire_groq_client", return_value=client):
            transcriber_module.transcribe_cloud(
                self._recording().reshape(-1, 1), "it", 1.0,
                "test-key", False, events.append, None,
            )

        self.assertEqual([event["status"] for event in events], ["result"])

    def test_float32_cloud_array_reuses_existing_storage(self):
        recording = self._recording()
        self.assertIs(transcriber_module._prepare_cloud_recording(recording), recording)

    def test_canonical_language_fast_path_keeps_same_string(self):
        language = "it"
        self.assertIs(transcriber_module._normalize_cloud_language(language), language)

    def test_finite_float_duration_fast_path_keeps_same_value(self):
        duration = 1.25
        self.assertIs(transcriber_module._normalize_recording_duration(duration), duration)

    def test_multi_channel_matrix_is_rejected_without_http(self):
        client = MagicMock(headers={"Authorization": "Bearer test"})
        events = []

        with patch.object(transcriber_module, "acquire_groq_client", return_value=client):
            transcriber_module.transcribe_cloud(
                np.zeros((SAMPLE_RATE, 2), dtype=np.float32), "it", 1.0,
                "test-key", False, events.append, None,
            )

        self.assertEqual([event["status"] for event in events], ["error", "ready"])
        client.send.assert_not_called()

    def test_auto_language_omits_language_multipart_field(self):
        response = MagicMock(status_code=200, content=b"ok")
        client = MagicMock(headers={"Authorization": "Bearer test"})
        client.send.return_value = response
        events = []

        with patch.object(transcriber_module, "acquire_groq_client", return_value=client):
            transcriber_module.transcribe_cloud(
                self._recording(), " AUTO ", 1.0,
                "test-key", False, events.append, None,
            )

        request = client.send.call_args.args[0]
        self.assertNotIn(b'name="language"', request.content)
        self.assertEqual([event["status"] for event in events], ["result"])

    def test_long_cloud_trim_preserves_speech_and_padding(self):
        # With CLOUD_SILENCE_PADDING_SECONDS=0.32 (5120), the same synthetic
        # recording is now fully preserved (start=0, end=160000) instead of
        # trimmed by 16 samples. The test validates speech+padding preservation
        # without hardcoding the old 0.16 padding.
        from whisper_engine.constants import CLOUD_SILENCE_PADDING_SECONDS
        padding = int(SAMPLE_RATE * CLOUD_SILENCE_PADDING_SECONDS)
        # Use old 0.16 padding to place speech near edges, verify new padding keeps it
        old_pad = int(SAMPLE_RATE * 0.16)
        recording = np.zeros(SAMPLE_RATE * 10, dtype=np.float32)
        recording[old_pad + 7 : -old_pad - 9] = 0.03

        trimmed = transcriber_module.trim_cloud_silence(recording)

        # With larger padding the whole file is kept (0..160000)
        self.assertEqual(trimmed.size, recording.size)
        self.assertTrue(np.all(trimmed[padding:-padding] == 0.03) or np.all(trimmed[old_pad:-old_pad] == 0.03))

    def test_http_429_becomes_rate_limit_and_ready(self):
        response = MagicMock(status_code=429, content=b"")
        response.raise_for_status.side_effect = RuntimeError("request failed")
        client = MagicMock(headers={"Authorization": "Bearer test"})
        client.send.return_value = response
        events = []

        with patch.object(transcriber_module, "acquire_groq_client", return_value=client):
            transcriber_module.transcribe_cloud(
                self._recording(), "it", 1.0, "test-key", False,
                events.append, None,
            )

        self.assertEqual([event["status"] for event in events], ["rate_limit", "ready"])
        response.close.assert_called_once()

    def test_transport_error_always_restores_ready_status(self):
        client = MagicMock(headers={"Authorization": "Bearer test"})
        client.send.side_effect = OSError("connection reset")
        events = []

        with patch.object(transcriber_module, "get_groq_client", return_value=client):
            transcriber_module.transcribe_cloud(
                self._recording(), "it", 1.0, "test-key", False,
                events.append, None,
            )

        self.assertEqual([event["status"] for event in events], ["error", "ready"])

    def test_invalid_response_bytes_still_produce_a_result(self):
        response = MagicMock(status_code=200, content=b"ok\xff")
        client = MagicMock(headers={"Authorization": "Bearer test"})
        client.send.return_value = response
        events = []

        with patch.object(transcriber_module, "acquire_groq_client", return_value=client):
            transcriber_module.transcribe_cloud(
                self._recording(), "it", 1.0, "test-key", False,
                events.append, None,
            )

        self.assertEqual(events[0]["status"], "result")
        self.assertIn("ok", events[0]["text"])

    def test_invalid_recording_duration_is_normalized_for_cloud_result(self):
        response = MagicMock(status_code=200, content=b"ok")
        client = MagicMock(headers={"Authorization": "Bearer test"})
        client.send.return_value = response
        events = []

        with patch.object(transcriber_module, "acquire_groq_client", return_value=client):
            transcriber_module.transcribe_cloud(
                self._recording(), "it", float("nan"), "test-key",
                False, events.append, None,
            )

        self.assertEqual(events[0]["duration"], 0.0)

    def test_empty_cloud_recording_skips_client_and_reports_ready(self):
        client = MagicMock(headers={"Authorization": "Bearer test"})
        events = []

        with patch.object(transcriber_module, "acquire_groq_client", return_value=client):
            transcriber_module.transcribe_cloud(
                np.zeros(0, dtype=np.float32), "it", 0.0,
                "test-key", False, events.append, None,
            )

        self.assertEqual([event["status"] for event in events], ["ready"])
        client.send.assert_not_called()

    def test_shutdown_skips_cloud_request(self):
        client = MagicMock(headers={"Authorization": "Bearer test"})
        events = []

        with patch.object(
            transcriber_module,
            "acquire_groq_client",
            return_value=client,
        ) as acquire:
            transcriber_module.transcribe_cloud(
                self._recording(), "it", 1.0, "test-key", True,
                events.append, None,
            )

        acquire.assert_not_called()
        client.send.assert_not_called()
        self.assertEqual(events, [])

    def test_http_timeout_restores_ready_status(self):
        client = MagicMock(headers={"Authorization": "Bearer test"})
        client.send.side_effect = transcriber_module.httpx.ReadTimeout("slow")
        events = []

        with patch.object(transcriber_module, "acquire_groq_client", return_value=client):
            transcriber_module.transcribe_cloud(
                self._recording(), "it", 1.0, "test-key", False,
                events.append, None,
            )

        self.assertEqual([event["status"] for event in events], ["error", "ready"])
        self.assertIn("Timeout", events[0]["message"])

    def test_shutdown_during_response_suppresses_late_result(self):
        response = MagicMock(status_code=200, content=b"late result")
        client = MagicMock(headers={"Authorization": "Bearer test"})
        shutdown = [False]

        def send(_request, stream=False):
            shutdown[0] = True
            return response

        client.send.side_effect = send
        events = []

        with patch.object(transcriber_module, "acquire_groq_client", return_value=client):
            transcriber_module.transcribe_cloud(
                self._recording(), "it", 1.0, "test-key",
                lambda: shutdown[0], events.append, None,
            )

        self.assertEqual(events, [])
        response.close.assert_called_once()


class TestGroqClientLifecycle(unittest.TestCase):
    def test_prewarm_rejects_stale_key_and_shutdown(self):
        engine = WhisperEngine()
        engine.groq_api_key = "new-key"
        with patch.object(transcriber_module, "get_groq_client") as get_client:
            engine.prepare_groq_client("old-key")
            engine._shutting_down = True
            engine.prepare_groq_client("new-key")
        get_client.assert_not_called()

    def test_client_close_errors_are_ignored_during_cleanup(self):
        class BrokenClient:
            def close(self):
                raise RuntimeError("already closed")

        transcriber_module._close_client(BrokenClient())

    def test_rotated_client_closes_outside_cache_lock(self):
        class FakeClient:
            def __init__(self):
                self.closed = False
                self.on_close = None

            def close(self):
                self.closed = True
                if self.on_close is not None:
                    self.on_close()

        old_client = FakeClient()
        new_client = FakeClient()
        transcriber_module.close_groq_client()
        old_client.on_close = lambda: transcriber_module.get_groq_client("new-key")

        with patch.object(
            transcriber_module,
            "create_groq_client",
            side_effect=[old_client, new_client],
        ):
            transcriber_module.get_groq_client("old-key")
            current = transcriber_module.get_groq_client("new-key")

        self.assertIs(current, new_client)
        self.assertTrue(old_client.closed)
        transcriber_module.close_groq_client()

    def test_rotated_client_waits_for_active_request_lease(self):
        class FakeClient:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        old_client = FakeClient()
        new_client = FakeClient()
        transcriber_module.close_groq_client()

        with patch.object(
            transcriber_module,
            "create_groq_client",
            side_effect=[old_client, new_client],
        ):
            leased = transcriber_module.acquire_groq_client("old-key")
            transcriber_module.get_groq_client("new-key")
            self.assertFalse(old_client.closed)
            transcriber_module.release_groq_client(leased)

        self.assertTrue(old_client.closed)
        transcriber_module.close_groq_client()


# ---------------------------------------------------------------------------
# Model path construction
# ---------------------------------------------------------------------------
class TestModelPath(unittest.TestCase):

    def test_download_model_path(self):
        """download_model should call hf_hub_download with models_dir as local_dir."""
        engine = WhisperEngine()
        engine.models_dir = "/home/user/.traflix/models"

        with patch("whisper_engine.model.hf_hub_download") as mock_dl, \
             patch("whisper_engine.model.verify_model", return_value=(True, "ok")), \
             patch("sys.stdout", new_callable=io.StringIO):
            engine.download_model("small")

        mock_dl.assert_called_once_with(
            repo_id="ggerganov/whisper.cpp",
            filename="ggml-small.bin",
            local_dir="/home/user/.traflix/models",
            local_dir_use_symlinks=False,
        )

    def test_load_model_path(self):
        """load_model should pass models_dir/ggml-{size}.bin to Model."""
        import os
        engine = WhisperEngine()
        engine.models_dir = "/models"

        with patch("whisper_engine.model.Model") as MockModel, \
             patch("whisper_engine.model.verify_model", return_value=(True, "ok")), \
             patch("sys.stdout", new_callable=io.StringIO):
            engine.load_model("large-v2")

        expected_path = os.path.join("/models", "ggml-large-v2.bin")
        MockModel.assert_called_once_with(expected_path, print_realtime=False, print_progress=False)

    def test_load_model_caches(self):
        """Calling load_model twice with the same size must NOT reload."""
        engine = WhisperEngine()
        engine.models_dir = "/models"

        with patch("whisper_engine.model.Model") as MockModel, \
             patch("whisper_engine.model.verify_model", return_value=(True, "ok")), \
             patch("sys.stdout", new_callable=io.StringIO):
            engine.load_model("small")
            engine.load_model("small")

        MockModel.assert_called_once()

    def test_load_model_reloads_on_size_change(self):
        """Switching model size should trigger a new Model load."""
        engine = WhisperEngine()
        engine.models_dir = "/models"

        with patch("whisper_engine.model.Model") as MockModel, \
             patch("whisper_engine.model.verify_model", return_value=(True, "ok")), \
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
        return engine

    def _mock_input_stream(self, engine, audio_blocks=None):
        """Helper to mock sd.InputStream context manager."""
        import sounddevice as sd
        import threading

        def fake_enter(self_inner):
            if audio_blocks:
                for block in audio_blocks:
                    mono = block[:, 0] if block.ndim > 1 else block
                    engine.audio_queue.put(mono.copy())
                def stop_later():
                    import time; time.sleep(0.15)
                    engine.stop_recording()
                threading.Thread(target=stop_later, daemon=True).start()
            else:
                engine.stop_recording()
            return MagicMock()
        sd.InputStream.return_value.__enter__ = fake_enter
        sd.InputStream.return_value.__exit__ = MagicMock(return_value=False)

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_transcribe_returns_result(self, mock_stdout):
        engine = self._setup_engine()
        fake_audio = np.random.randn(BLOCK_SIZE, 1).astype(np.float32)

        mock_segment = MagicMock()
        mock_segment.text = "ciao mondo"
        engine.model.transcribe.return_value = [mock_segment]

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
        engine.model.transcribe.return_value = [mock_segment]

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
        self.assertTrue(any(p.get("status") == "ready" for p in parsed_lines))

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_provider_is_snapshotted_for_the_active_recording(self, mock_stdout):
        engine = self._setup_engine()
        engine.provider = "cloud"
        fake_audio = np.ones((BLOCK_SIZE, 1), dtype=np.float32)
        import sounddevice as sd

        def fake_enter(_stream):
            engine.audio_queue.put(fake_audio[:, 0].copy())
            engine.provider = "local"
            engine.stop_recording()
            return MagicMock()

        sd.InputStream.return_value.__enter__ = fake_enter
        sd.InputStream.return_value.__exit__ = MagicMock(return_value=False)

        def dispatch_cloud(*_args):
            engine.provider = "local"

        with patch.object(engine, "_transcribe_cloud", side_effect=dispatch_cloud) as cloud, \
             patch.object(engine, "_transcribe_local") as local:
            engine.transcribe(0, "small")

        cloud.assert_called_once()
        local.assert_not_called()

    def test_rapid_cloud_restart_is_not_queued_behind_previous_request(self):
        engine = self._setup_engine()
        engine.provider = "cloud"
        events = []
        first_listening = threading.Event()
        second_listening = threading.Event()
        cloud_request_started = threading.Event()
        release_cloud_request = threading.Event()
        listening_count = 0

        class FakeInputStream:
            def __init__(self, **kwargs):
                self.callback = kwargs["callback"]

            def __enter__(self):
                self.callback(
                    np.zeros((BLOCK_SIZE, 1), dtype=np.float32),
                    BLOCK_SIZE,
                    None,
                    None,
                )
                return self

            def __exit__(self, *_args):
                return False

        def log(event):
            nonlocal listening_count
            events.append(event)
            if event.get("status") == "listening":
                listening_count += 1
                if listening_count == 1:
                    first_listening.set()
                elif listening_count == 2:
                    second_listening.set()

        def fake_cloud(*_args):
            cloud_request_started.set()
            release_cloud_request.wait(timeout=2)

        engine.log = log
        engine._transcribe_cloud = fake_cloud
        engine.audio_callback = (
            lambda _indata, _frames, _time, _status, capture_queue, **_kwargs:
            capture_queue.put(np.zeros((BLOCK_SIZE,), dtype=np.float32))
        )

        import sounddevice as sd

        engine.prepare_transcription_worker()
        first = None
        second = None
        try:
            with patch.object(sd, "InputStream", FakeInputStream):
                first = engine.start_transcription(None, "small")
                self.assertTrue(first_listening.wait(timeout=1))
                engine.stop_recording()
                self.assertTrue(cloud_request_started.wait(timeout=1))

                second = engine.start_transcription(None, "small")
                self.assertTrue(
                    second_listening.wait(timeout=1),
                    "the second recording must start while the first cloud request is pending",
                )
                engine.stop_recording()
                release_cloud_request.set()

            first.result(timeout=2)
            second.result(timeout=2)
        finally:
            release_cloud_request.set()
            if engine._active_session is not None:
                engine.stop_recording()
            if first is not None:
                first.result(timeout=2)
            if second is not None:
                second.result(timeout=2)
            engine.close_transcription_worker()

        self.assertEqual(
            [event.get("status") for event in events].count("listening"),
            2,
        )


class TestRecordingSession(unittest.TestCase):
    def test_stop_is_idempotent_and_wakes_only_its_queue(self):
        session = _RecordingSession()
        # Immediate stop (drain 0) preserves old test semantics
        session.stop(drain_seconds=0)
        session.stop(drain_seconds=0)

        self.assertFalse(session.active.is_set())
        self.assertFalse(session.is_active)
        self.assertIsNone(session.queue.get_nowait())
        self.assertTrue(session.queue.empty())

    def test_stop_with_drain_keeps_tail_window(self):
        session = _RecordingSession()
        session.stop(drain_seconds=0.22)
        # During drain, is_active stays True and queue not yet poisoned
        self.assertFalse(session.active.is_set())
        self.assertTrue(session.is_active)
        self.assertTrue(session.queue.empty())
        # After drain, sentinel appears and is_active flips
        import time
        time.sleep(0.26)
        self.assertFalse(session.is_active)
        self.assertIsNone(session.queue.get_nowait())

    def test_stopped_session_callback_does_not_enqueue_audio(self):
        engine = WhisperEngine()
        session = _RecordingSession()
        session.stop(drain_seconds=0)
        block = np.ones((BLOCK_SIZE, 1), dtype=np.float32)

        engine.audio_callback(
            block,
            BLOCK_SIZE,
            None,
            None,
            session.queue,
            recording_active=session.is_active,
        )

        self.assertIsNone(session.queue.get_nowait())
        self.assertTrue(session.queue.empty())

    def test_draining_callback_still_enqueues_tail(self):
        engine = WhisperEngine()
        session = _RecordingSession()
        session.stop(drain_seconds=0.22)
        block = np.ones((BLOCK_SIZE, 1), dtype=np.float32)
        engine.audio_callback(
            block,
            BLOCK_SIZE,
            None,
            None,
            session.queue,
            recording_active=session.is_active,
        )
        # During drain, audio must still be enqueued (tail capture)
        self.assertFalse(session.queue.empty())
        # Cleanup drain timer
        import time
        time.sleep(0.26)
        # Drain remaining
        while not session.queue.empty():
            try:
                session.queue.get_nowait()
            except Exception:
                break


# ---------------------------------------------------------------------------
# Download model error handling
# ---------------------------------------------------------------------------
class TestDownloadModel(unittest.TestCase):

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_download_error_logged(self, mock_stdout):
        """If hf_hub_download raises, the error is logged as JSON."""
        engine = WhisperEngine()
        engine.models_dir = "/models"

        with patch("whisper_engine.model.hf_hub_download", side_effect=OSError("disk full")):
            engine.download_model("tiny")

        output_lines = mock_stdout.getvalue().strip().split("\n")
        parsed = [json.loads(l) for l in output_lines if l]
        error_logs = [p for p in parsed if p.get("status") == "download_error"]
        self.assertTrue(len(error_logs) >= 1)
        self.assertIn("disk full", error_logs[0]["message"])

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_download_success_logs_complete(self, mock_stdout):
        engine = WhisperEngine()
        engine.models_dir = "/models"

        with patch("whisper_engine.model.hf_hub_download"), \
             patch("whisper_engine.model.verify_model", return_value=(True, "ok")):
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
        self.assertEqual(BLOCK_SIZE, 512)


if __name__ == "__main__":
    unittest.main()
