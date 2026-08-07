import io
import unittest
import wave
from unittest.mock import patch

import httpx
import numpy as np

from whisper_engine import transcriber
from whisper_engine.constants import GROQ_TRANSCRIPTION_URL, SAMPLE_RATE
from whisper_engine.transcriber import encode_wav


class TestCloudPayload(unittest.TestCase):
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
            headers={"Authorization": "Bearer fake-key"},
        )
        events = []
        transcriber.close_groq_client()
        with patch.object(transcriber, "create_groq_client", return_value=client):
            transcriber.transcribe_cloud(
                np.zeros(160, dtype=np.float32),
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
        self.assertIn(b"whisper-large-v3-turbo", request.content)
        self.assertEqual(events[-1]["text"], "ciao")


if __name__ == "__main__":
    unittest.main()
