import hashlib
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

import numpy as np

from whisper_engine import speech_gate


class _VadModel:
    def __init__(self):
        self.blocks = []
        self.events = []
        self.behavior = lambda _block: False
        self.reset_error_at = None
        self.reset_count = 0

    def window_size(self):
        return 576

    def reset(self):
        self.reset_count += 1
        self.events.append(("reset", threading.get_ident()))
        if self.reset_count == self.reset_error_at:
            raise RuntimeError("synthetic reset failure")

    def is_speech(self, block):
        self.blocks.append(block.copy())
        self.events.append(("infer", threading.get_ident()))
        return self.behavior(block)


class TestSpeechGate(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "silero_vad.onnx"
        self.model_bytes = b"synthetic model bytes"
        self.path.write_bytes(self.model_bytes)
        self.model = _VadModel()
        self.configs = []

        def create(config):
            self.configs.append(config)
            return self.model

        self.backend = SimpleNamespace(
            VadModelConfig=lambda: SimpleNamespace(silero_vad=SimpleNamespace()),
            VadModel=SimpleNamespace(create=create),
        )

    def gate(self, backend=None):
        with (
            patch.object(speech_gate, "SILERO_VAD_MODEL_SHA256", hashlib.sha256(self.model_bytes).hexdigest()),
            patch.object(speech_gate, "SILERO_VAD_MODEL_BYTES", len(self.model_bytes)),
            patch.dict("sys.modules", {"sherpa_onnx": backend or self.backend}),
        ):
            gate = speech_gate.SpeechGate(self.path)
        self.addCleanup(gate.close)
        return gate

    def test_preloaded_model_is_reused_with_one_cpu_thread(self):
        gate = self.gate()
        self.assertTrue(gate.available)
        self.assertIs(gate.detect(np.ones(1600, np.float32) * 0.3), False)
        self.assertIs(gate.detect(np.ones(1600, np.float32) * 0.3), False)
        self.assertEqual(len(self.configs), 1)
        self.assertEqual(self.configs[0].num_threads, 1)
        self.assertEqual(self.configs[0].provider, "cpu")
        self.assertEqual(self.configs[0].sample_rate, 16000)
        self.assertEqual(self.configs[0].silero_vad.window_size, 512)

    def test_missing_backend_and_model_do_not_claim_silence(self):
        missing = speech_gate.SpeechGate(self.path.with_name("missing.onnx"))
        self.assertFalse(missing.available)
        self.assertIsNone(missing.detect(np.zeros(1600, np.float32)))
        with (
            patch.object(speech_gate, "SILERO_VAD_MODEL_SHA256", hashlib.sha256(self.model_bytes).hexdigest()),
            patch.object(speech_gate, "SILERO_VAD_MODEL_BYTES", len(self.model_bytes)),
            patch.dict("sys.modules", {"sherpa_onnx": None}),
        ):
            unavailable = speech_gate.SpeechGate(self.path)
        self.assertFalse(unavailable.available)
        self.assertIsNone(unavailable.detect(np.ones(1600, np.float32)))

    def test_corrupt_model_is_rejected_before_entering_native_backend(self):
        with patch.dict("sys.modules", {"sherpa_onnx": self.backend}):
            gate = speech_gate.SpeechGate(self.path)
        self.assertFalse(gate.available)
        self.assertIsNone(gate.detect(np.ones(1600, np.float32)))
        self.assertEqual(self.configs, [])

    def test_partial_frame_and_quiet_audio_are_preserved(self):
        gate = self.gate()
        self.model.behavior = lambda block: bool(np.any(block))
        recording = np.zeros(17, np.float32)
        recording[-1] = 0.00003
        recording.flags.writeable = False
        original = recording.copy()
        self.assertIs(gate.detect(recording), True)
        np.testing.assert_array_equal(recording, original)
        self.assertEqual(self.model.blocks[0].shape, (576,))
        self.assertAlmostEqual(float(self.model.blocks[0][64 + 16]), 0.2, places=6)
        self.assertEqual(self.model.reset_count, 2)

    def test_windows_use_v5_context_without_dropping_final_samples(self):
        gate = self.gate()
        recording = np.linspace(0.3, 0.9, 1100, dtype=np.float32)[::-1]
        original = recording.copy()
        self.assertIs(gate.detect(recording), False)
        np.testing.assert_array_equal(recording, original)
        reconstructed = np.concatenate([block[64:] for block in self.model.blocks])
        np.testing.assert_array_equal(reconstructed[:recording.size], original)
        np.testing.assert_array_equal(self.model.blocks[1][:64], self.model.blocks[0][-64:])
        self.assertFalse(np.any(reconstructed[recording.size:]))
        self.assertEqual(self.model.reset_count, 2)

    def test_early_success_resets_before_the_next_recording(self):
        gate = self.gate()
        self.model.behavior = lambda _block: True
        self.assertIs(gate.detect(np.ones(4000, np.float32) * 0.3), True)
        self.assertEqual(len(self.model.blocks), 1)
        self.model.behavior = lambda _block: False
        self.assertIs(gate.detect(np.ones(600, np.float32) * 0.3), False)
        self.assertEqual(self.model.reset_count, 4)
        self.assertEqual(self.model.events[0][0], "reset")
        self.assertEqual(self.model.events[2:4][0][0], "reset")
        self.assertEqual(self.model.events[2:4][1][0], "reset")

    def test_inference_and_cleanup_failures_return_unavailable(self):
        for cleanup_failure in (False, True):
            with self.subTest(cleanup_failure=cleanup_failure):
                self.model = _VadModel()
                gate = self.gate()
                if cleanup_failure:
                    self.model.reset_error_at = 2
                else:
                    def fail(_block):
                        raise RuntimeError("synthetic inference failure")
                    self.model.behavior = fail
                self.assertIsNone(gate.detect(np.ones(600, np.float32) * 0.3))
                self.assertFalse(gate.available)
                self.assertGreaterEqual(self.model.reset_count, 2)
                self.assertIsNone(gate.detect(np.ones(600, np.float32) * 0.3))

    def test_invalid_audio_does_not_disable_a_healthy_gate(self):
        gate = self.gate()
        for recording in (
            np.zeros((2, 2), np.float32),
            np.array([np.nan], np.float32),
            np.array([np.inf], np.float32),
            np.array([1j]),
            np.array(["invalid"]),
        ):
            with self.subTest(dtype=str(recording.dtype), shape=recording.shape):
                self.assertIsNone(gate.detect(recording))
        self.assertTrue(gate.available)
        self.assertEqual(self.model.blocks, [])

    def test_concurrent_recordings_do_not_interleave_recurrent_state(self):
        gate = self.gate()
        started = threading.Event()
        release = threading.Event()
        second_started = threading.Event()
        results = []

        def detect_first(_block):
            started.set()
            release.wait(timeout=2)
            return True

        self.model.behavior = detect_first
        first = threading.Thread(target=lambda: results.append(gate.detect(np.ones(600, np.float32))))
        def second_detect():
            second_started.set()
            results.append(gate.detect(np.ones(600, np.float32)))
        second = threading.Thread(target=second_detect)
        first.start()
        self.assertTrue(started.wait(timeout=1))
        second.start()
        self.assertTrue(second_started.wait(timeout=1))
        self.assertEqual(len(self.model.blocks), 1)
        release.set()
        first.join(timeout=2)
        second.join(timeout=2)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(results, [True, True])
        self.assertEqual([event[0] for event in self.model.events], ["reset", "infer", "reset"] * 2)

    def test_close_waits_for_active_inference_then_prevents_reuse(self):
        gate = self.gate()
        started = threading.Event()
        release = threading.Event()
        closing = threading.Event()
        closed = threading.Event()
        def blocked(_block):
            started.set()
            release.wait(timeout=2)
            return True
        self.model.behavior = blocked
        worker = threading.Thread(target=lambda: gate.detect(np.ones(600, np.float32)))
        def close():
            closing.set()
            gate.close()
            closed.set()
        closer = threading.Thread(target=close)
        worker.start()
        self.assertTrue(started.wait(timeout=1))
        closer.start()
        self.assertTrue(closing.wait(timeout=1))
        self.assertFalse(closed.is_set())
        release.set()
        worker.join(timeout=2)
        closer.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertFalse(closer.is_alive())
        self.assertTrue(closed.is_set())
        self.assertFalse(gate.available)
        self.assertIsNone(gate.detect(np.ones(600, np.float32)))
        gate.close()


@unittest.skipUnless(os.environ.get("TRAFLIX_SPEECH_VAD_MODEL"), "set TRAFLIX_SPEECH_VAD_MODEL for native VAD tests")
class TestNativeSpeechGate(unittest.TestCase):
    def setUp(self):
        self.gate = speech_gate.SpeechGate(os.environ["TRAFLIX_SPEECH_VAD_MODEL"])
        self.addCleanup(self.gate.close)
        self.assertTrue(self.gate.available)

    def test_silence_hum_white_noise_and_clicks_have_no_voice(self):
        rng = np.random.default_rng(421)
        for length in (0, 160, 800, 32000, 160000):
            with self.subTest(silence_samples=length):
                self.assertIs(self.gate.detect(np.zeros(length, np.float32)), False)
        for scale in (0.001, 0.03, 0.15):
            for name, audio in (
                ("white", rng.normal(0, scale, 32000).astype(np.float32)),
                ("hum", (np.sin(np.arange(32000) * 2 * np.pi * 50 / 16000) * scale).astype(np.float32)),
            ):
                with self.subTest(noise=name, scale=scale):
                    self.assertIs(self.gate.detect(audio), False)
        for spacing in (32000, 1600):
            clicks = np.zeros(32000, np.float32)
            clicks[::spacing] = 0.9
            self.assertIs(self.gate.detect(clicks), False)

    def test_generated_fast_and_quiet_speech_including_single_words(self):
        fixture_dir = os.environ.get("TRAFLIX_SPEECH_VAD_FIXTURES")
        if not fixture_dir:
            self.skipTest("set TRAFLIX_SPEECH_VAD_FIXTURES to the generated TTS benchmark directory")
        root = Path(fixture_dir)
        paths = sorted([*root.glob("*-rate*.wav"), *(root / "vad").glob("*-rate*.wav")])
        self.assertEqual(len(paths), 14, "expected eight generated sentences and six single words")
        for path in paths:
            with wave.open(str(path), "rb") as wav:
                self.assertEqual(wav.getnchannels(), 1)
                self.assertEqual(wav.getframerate(), 16000)
                self.assertEqual(wav.getsampwidth(), 2)
                samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32) / 32768
            for gain in (1, 0.03, 0.003):
                with self.subTest(fixture=path.name, gain=gain):
                    quiet = samples * gain
                    original = quiet.copy()
                    self.assertIs(self.gate.detect(quiet), True)
                    np.testing.assert_array_equal(quiet, original)
            if path.parent.name == "vad":
                nonzero = np.flatnonzero(samples)
                word_only = samples[nonzero[0]:nonzero[-1] + 1]
                for gain in (1, 0.003):
                    with self.subTest(fixture=path.name, word_only=True, gain=gain):
                        self.assertIs(self.gate.detect(word_only * gain), True)


if __name__ == "__main__":
    unittest.main()
