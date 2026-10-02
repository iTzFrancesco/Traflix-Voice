import io
import unittest
import wave
from unittest.mock import patch

import httpx
import numpy as np

from whisper_engine import transcriber
from whisper_engine.constants import (
    CLOUD_SILENCE_PADDING_SECONDS,
    CLOUD_SILENCE_THRESHOLD,
    GROQ_MULTIPART_BOUNDARY,
    GROQ_TRANSCRIPTION_URL,
    SAMPLE_RATE,
)
from whisper_engine.transcriber import encode_cloud_multipart, encode_wav, trim_cloud_silence


class TestCloudPayload(unittest.TestCase):
    def test_encode_cloud_multipart_contains_expected_fields(self):
        payload = encode_cloud_multipart(encode_wav(np.zeros(160, dtype=np.float32)), "it")
        self.assertIn(b'name="model"', payload)
        self.assertIn(b'name="response_format"', payload)
        self.assertIn(b'name="language"', payload)
        self.assertIn(b'filename="audio.wav"', payload)
        self.assertIn(GROQ_MULTIPART_BOUNDARY.encode("ascii"), payload)

    def test_encode_cloud_multipart_omits_language_for_auto_detection(self):
        payload = encode_cloud_multipart(encode_wav(np.zeros(160, dtype=np.float32)), None)
        self.assertNotIn(b'name="language"', payload)
        self.assertIn(b'filename="audio.wav"', payload)

    def test_cloud_payload_uses_turbo_as_its_only_model(self):
        payload = encode_cloud_multipart(encode_wav(np.zeros(160, dtype=np.float32)), "it")

        self.assertIn(b"whisper-large-v3-turbo\r\n", payload)
        self.assertNotIn(b"whisper-large-v3\r\n", payload)

    def test_trim_cloud_silence_keeps_quiet_speech_and_padding(self):
        quiet_speech = np.full(8000, 0.005, dtype=np.float32)
        recording = np.concatenate(
            [np.zeros(16000, dtype=np.float32), quiet_speech, np.zeros(16000, dtype=np.float32)]
        )

        trimmed = trim_cloud_silence(recording)

        self.assertLess(trimmed.size, recording.size)
        self.assertGreater(trimmed.size, quiet_speech.size)
        self.assertTrue(np.any(trimmed == 0.005))

    def test_trim_cloud_silence_returns_empty_view_for_silence(self):
        recording = np.zeros(4000, dtype=np.float32)
        trimmed = trim_cloud_silence(recording)

        self.assertEqual(trimmed.size, 0)
        self.assertFalse(trimmed.flags.owndata)

    def test_trim_preserves_speech_below_the_old_volume_gate(self):
        for length in (SAMPLE_RATE * 3, SAMPLE_RATE * 12):
            with self.subTest(length=length):
                recording = np.zeros(length, dtype=np.float32)
                recording[SAMPLE_RATE : length - SAMPLE_RATE] = 0.001
                trimmed = trim_cloud_silence(recording)
                self.assertGreater(trimmed.size, 0)
                self.assertEqual(
                    np.count_nonzero(trimmed), length - SAMPLE_RATE * 2
                )

    def test_trim_preserves_weak_word_edges_far_from_loud_vowels(self):
        for length in (SAMPLE_RATE * 4, SAMPLE_RATE * 12):
            with self.subTest(length=length):
                recording = np.zeros(length, dtype=np.float32)
                recording[SAMPLE_RATE : length - SAMPLE_RATE] = 0.0002
                recording[SAMPLE_RATE * 2 : SAMPLE_RATE * 3] = 0.1
                trimmed = trim_cloud_silence(recording)
                self.assertEqual(
                    np.count_nonzero(trimmed), length - SAMPLE_RATE * 2
                )

    def test_trim_cloud_silence_leaves_empty_input_unchanged(self):
        recording = np.array([], dtype=np.float32)
        self.assertIs(trim_cloud_silence(recording), recording)

    def test_trim_cloud_silence_scans_long_recording_without_losing_edges(self):
        from whisper_engine.constants import CLOUD_SILENCE_PADDING_SECONDS
        recording = np.zeros(320000, dtype=np.float32)
        recording[120000:200000] = -0.005

        trimmed = trim_cloud_silence(recording)

        padding = int(SAMPLE_RATE * CLOUD_SILENCE_PADDING_SECONDS)
        self.assertEqual(trimmed.size, 80000 + padding * 2)
        self.assertAlmostEqual(float(trimmed[padding]), -0.005)

    def test_trim_cloud_silence_ignores_non_finite_samples(self):
        recording = np.full(160000, np.nan, dtype=np.float32)
        self.assertEqual(trim_cloud_silence(recording).size, 0)

    def test_encode_wav_matches_groq_audio_contract(self):
        samples = np.array([-2.0, -1.0, -0.25, 0.0, 0.25, 1.0, 2.0], dtype=np.float32)
        payload = encode_wav(samples).getvalue()

        with wave.open(io.BytesIO(payload), "rb") as wav:
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getsampwidth(), 2)
            self.assertEqual(wav.getframerate(), SAMPLE_RATE)
            self.assertEqual(wav.getnframes(), len(samples))
            pcm = np.frombuffer(wav.readframes(len(samples)), dtype="<i2")
        np.testing.assert_array_equal(
            pcm,
            np.array([-32767, -32767, -8191, 0, 8191, 32767, 32767], dtype=np.int16),
        )

    def test_encode_wav_normalized_fast_path_preserves_samples(self):
        samples = np.linspace(-0.9, 0.9, SAMPLE_RATE * 2, dtype=np.float32)
        payload = encode_wav(samples).getvalue()

        with wave.open(io.BytesIO(payload), "rb") as wav:
            pcm = np.frombuffer(wav.readframes(len(samples)), dtype="<i2")

        np.testing.assert_array_equal(pcm, (samples * 32767.0).astype(np.int16))

    def test_direct_multipart_does_not_materialize_an_intermediate_wav(self):
        samples = np.linspace(-0.9, 0.9, SAMPLE_RATE * 30, dtype=np.float32)
        expected = encode_cloud_multipart(encode_wav(samples, assume_normalized=True), "it")
        with patch.object(transcriber, "_encode_wav_payload", side_effect=AssertionError("WAV copy")):
            actual = transcriber.encode_cloud_multipart_from_recording(samples, "it", True)
        self.assertEqual(actual, expected)

    def test_direct_multipart_matches_wav_helper_for_layouts_and_languages(self):
        source = np.linspace(-1.0, 1.0, SAMPLE_RATE * 9 + 17, dtype=np.float32)
        for samples in (source[:0], source[:1], source[:512], source, source[::2], source[::-1]):
            before = samples.copy()
            for language in (None, "it", "en", "fr", "de", "es", "pt", "ja", "custom-è"):
                for normalized in (False, True):
                    expected = encode_cloud_multipart(encode_wav(samples, normalized), language)
                    actual = transcriber.encode_cloud_multipart_from_recording(samples, language, normalized)
                    self.assertEqual(actual, expected)
                    np.testing.assert_array_equal(samples, before)

    def test_direct_multipart_clips_untrusted_input_without_mutating_it(self):
        source = np.array([-2.0, -1.0, -0.0002, 0.0, 0.0002, 1.0, 2.0], dtype=np.float32)
        before = source.copy()
        expected = encode_cloud_multipart(encode_wav(source), None)
        self.assertEqual(transcriber.encode_cloud_multipart_from_recording(source, None), expected)
        np.testing.assert_array_equal(source, before)

    def test_long_trim_with_early_onset_does_not_scan_the_interior(self):
        class NoInteriorReductions(np.ndarray):
            def max(self, *args, **kwargs):
                raise AssertionError("unnecessary full recording maximum")

            def min(self, *args, **kwargs):
                raise AssertionError("unnecessary full recording minimum")

        samples = np.full(SAMPLE_RATE * 30, -0.0002, dtype=np.float32)
        samples[:1600] = 0
        samples[-3520:] = 0
        trimmed = trim_cloud_silence(samples.view(NoInteriorReductions))
        np.testing.assert_array_equal(trimmed, samples)

    def test_trim_matches_exact_full_mask_across_scan_boundaries(self):
        rng = np.random.default_rng(42)
        padding = int(SAMPLE_RATE * CLOUD_SILENCE_PADDING_SECONDS)
        for length in (1, 511, SAMPLE_RATE * 8, SAMPLE_RATE * 8 + 1, SAMPLE_RATE * 30 + 17):
            for layout in ("silence", "quiet", "negative", "sparse", "non-finite", "reversed"):
                samples = np.zeros(length, dtype=np.float32)
                if layout in ("quiet", "negative", "reversed"):
                    samples[length // 7:length * 6 // 7 + 1] = -0.0002 if layout == "negative" else 0.0002
                elif layout == "sparse":
                    samples[rng.integers(0, length, size=10)] = -0.03
                elif layout == "non-finite":
                    samples[:] = np.nan
                    samples[length // 2] = 0.0002
                if layout == "reversed":
                    samples = samples[::-1]
                original = samples.copy()
                active = np.flatnonzero(np.abs(samples) >= CLOUD_SILENCE_THRESHOLD)
                expected = (samples[max(0, active[0] - padding):min(length, active[-1] + padding + 1)]
                            if active.size else samples[:0])
                np.testing.assert_array_equal(trim_cloud_silence(samples), expected)
                np.testing.assert_array_equal(samples, original)

    def test_cloud_request_uses_direct_transcription_endpoint(self):
        captured = {}

        def handler(request):
            captured["request"] = request
            return httpx.Response(200, text=" ciao ", request=request)

        client = httpx.Client(
            transport=httpx.MockTransport(handler),
            headers={
                "Authorization": "Bearer fake-key",
                "Content-Type": f"multipart/form-data; boundary={GROQ_MULTIPART_BOUNDARY}",
            },
        )
        events = []
        transcriber.close_groq_client()
        with patch.object(transcriber, "create_groq_client", return_value=client):
            transcriber.transcribe_cloud(
                np.full(160, 0.03, dtype=np.float32),
                "it",
                0.01,
                "fake-key",
                False,
                events.append,
                None,
            )
        transcriber.close_groq_client()

        request = captured["request"]
        self.assertEqual(str(request.url), GROQ_TRANSCRIPTION_URL)
        self.assertEqual(request.headers["authorization"], "Bearer fake-key")
        self.assertEqual(
            request.headers["content-type"],
            f"multipart/form-data; boundary={GROQ_MULTIPART_BOUNDARY}",
        )
        self.assertIn(b"whisper-large-v3-turbo", request.content)
        self.assertEqual(events[-1]["text"], "ciao")

    def test_silent_cloud_recording_skips_network_request(self):
        events = []
        with patch.object(transcriber, "acquire_groq_client") as get_client:
            transcriber.transcribe_cloud(
                np.zeros(16000, dtype=np.float32),
                "it",
                1.0,
                "fake-key",
                False,
                events.append,
                None,
            )

        get_client.assert_not_called()
        self.assertEqual(events[-1]["status"], "ready")


if __name__ == "__main__":
    unittest.main()
