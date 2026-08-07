import unittest

import numpy as np

from whisper_engine.audio import calculate_volume


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


if __name__ == "__main__":
    unittest.main()
