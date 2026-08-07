import io
import unittest
import wave
from unittest.mock import patch

import httpx
import numpy as np

from whisper_engine import transcriber
from whisper_engine.constants import GROQ_MULTIPART_BOUNDARY, GROQ_TRANSCRIPTION_URL, SAMPLE_RATE
from whisper_engine.transcriber import encode_cloud_multipart, encode_wav, trim_cloud_silence


class TestCloudPayload(unittest.TestCase):
    def test_encode_cloud_multipart_contains_expected_fields(self):
        payload = encode_cloud_multipart(encode_wav(np.zeros(160, dtype=np.float32)), "it")
        self.assertIn(b'name="model"', payload)
        self.assertIn(b'name="response_format"', payload)
        self.assertIn(b'name="language"', payload)
        self.assertIn(b'filename="audio.wav"', payload)
        self.assertIn(GROQ_MULTIPART_BOUNDARY.encode("ascii"), payload)

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

    def test_trim_cloud_silence_leaves_empty_input_unchanged(self):
        recording = np.array([], dtype=np.float32)
        self.assertIs(trim_cloud_silence(recording), recording)

    def test_trim_cloud_silence_scans_long_recording_without_losing_edges(self):
        recording = np.zeros(320000, dtype=np.float32)
        recording[120000:200000] = -0.005

        trimmed = trim_cloud_silence(recording)

        padding = int(SAMPLE_RATE * 0.16)
        self.assertEqual(trimmed.size, 80000 + padding * 2)
        self.assertAlmostEqual(float(trimmed[padding]), -0.005)

    def test_trim_cloud_silence_ignores_non_finite_samples(self):
        recording = np.full(160000, np.nan, dtype=np.float32)
        self.assertEqual(trim_cloud_silence(recording).size, 0)

    def test_encode_wav_matches_groq_audio_contract(self):
        samples = np.array([-1.0, -0.25, 0.0, 0.25, 1.0], dtype=np.float32)
        payload = encode_wav(samples).getvalue()

        with wave.open(io.BytesIO(payload), "rb") as wav:
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getsampwidth(), 2)
            self.assertEqual(wav.getframerate(), SAMPLE_RATE)
            self.assertEqual(wav.getnframes(), len(samples))

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
        with patch.object(transcriber, "get_groq_client") as get_client:
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
