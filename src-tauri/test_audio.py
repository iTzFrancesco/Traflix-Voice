import unittest

import numpy as np

from whisper_engine.audio import apply_automatic_gain, calculate_volume


class TestVolumeMeter(unittest.TestCase):
    def test_silence_is_zero(self):
        self.assertEqual(calculate_volume(np.zeros((4000, 1), dtype=np.float32)), 0)

    def test_quiet_signal_is_visible(self):
        signal = np.full((4000, 1), 0.005, dtype=np.float32)
        self.assertGreater(calculate_volume(signal), 0)

    def test_louder_signal_is_higher(self):
        quiet = np.full((4000, 1), 0.01, dtype=np.float32)
        loud = np.full((4000, 1), 0.05, dtype=np.float32)
        self.assertGreater(calculate_volume(loud), calculate_volume(quiet))

    def test_level_does_not_depend_on_block_length(self):
        short = np.full((1600, 1), 0.02, dtype=np.float32)
        long = np.full((4000, 1), 0.02, dtype=np.float32)
        self.assertEqual(calculate_volume(short), calculate_volume(long))

    def test_invalid_samples_are_ignored(self):
        samples = np.array([[np.nan], [np.inf], [-np.inf], [0.01]], dtype=np.float32)
        self.assertGreaterEqual(calculate_volume(samples), 0)


class TestAutomaticGain(unittest.TestCase):
    def test_boosts_quiet_speech_toward_target(self):
        from whisper_engine.constants import SAMPLE_RATE

        time = np.arange(SAMPLE_RATE // 2, dtype=np.float32) / SAMPLE_RATE
        speech = (0.01 * np.sin(2 * np.pi * 220 * time)).astype(np.float32)
        recording = np.concatenate([np.zeros(SAMPLE_RATE // 5, dtype=np.float32), speech])
        original_peak = float(np.max(np.abs(recording)))

        apply_automatic_gain(recording)

        self.assertGreater(float(np.max(np.abs(recording))), original_peak * 2)
        self.assertLessEqual(float(np.max(np.abs(recording))), 0.98)

    def test_boosts_continuous_quiet_speech_without_silence(self):
        from whisper_engine.constants import SAMPLE_RATE

        time = np.arange(SAMPLE_RATE // 2, dtype=np.float32) / SAMPLE_RATE
        recording = (0.01 * np.sin(2 * np.pi * 220 * time)).astype(np.float32)
        original_peak = float(np.max(np.abs(recording)))

        apply_automatic_gain(recording)

        self.assertGreater(float(np.max(np.abs(recording))), original_peak * 2)
        self.assertLessEqual(float(np.max(np.abs(recording))), 0.98)

    def test_silence_is_not_amplified(self):
        recording = np.zeros(4096, dtype=np.float32)
        original = recording.copy()

        apply_automatic_gain(recording)

        np.testing.assert_array_equal(recording, original)

    def test_loud_speech_is_not_boosted(self):
        from whisper_engine.constants import SAMPLE_RATE

        time = np.arange(SAMPLE_RATE // 4, dtype=np.float32) / SAMPLE_RATE
        recording = (0.3 * np.sin(2 * np.pi * 220 * time)).astype(np.float32)
        original = recording.copy()

        apply_automatic_gain(recording)

        np.testing.assert_array_equal(recording, original)

    def test_peak_ceiling_prevents_clipping(self):
        from whisper_engine.constants import SAMPLE_RATE

        time = np.arange(SAMPLE_RATE // 2, dtype=np.float32) / SAMPLE_RATE
        speech = (0.01 * np.sin(2 * np.pi * 220 * time)).astype(np.float32)
        recording = np.concatenate([np.zeros(320, dtype=np.float32), speech])
        recording[320 + 100] = 0.9

        apply_automatic_gain(recording)

        self.assertLessEqual(float(np.max(np.abs(recording))), 0.981)


if __name__ == "__main__":
    unittest.main()
