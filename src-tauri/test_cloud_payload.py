import io
import unittest
import wave

import numpy as np

from whisper_engine.transcriber import encode_wav
from whisper_engine.constants import SAMPLE_RATE


class TestCloudPayload(unittest.TestCase):
    def test_encode_wav_matches_groq_audio_contract(self):
        samples = np.array([-1.0, -0.25, 0.0, 0.25, 1.0], dtype=np.float32)
        payload = encode_wav(samples).getvalue()

        with wave.open(io.BytesIO(payload), "rb") as wav:
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getsampwidth(), 2)
            self.assertEqual(wav.getframerate(), SAMPLE_RATE)
            self.assertEqual(wav.getnframes(), len(samples))


if __name__ == "__main__":
    unittest.main()
