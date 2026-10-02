import unittest
from unittest import mock

import numpy as np

from whisper_engine import audio
from whisper_engine.audio import apply_automatic_gain, calculate_volume
from whisper_engine.constants import (
    AUTO_GAIN_ACTIVITY_THRESHOLD,
    AUTO_GAIN_MAX,
    AUTO_GAIN_PEAK_CEILING,
    AUTO_GAIN_TARGET_RMS,
    SAMPLE_RATE,
)


def _gain_before_finite_fast_path(recording):
    """Reference implementation with the original unconditional sanitization."""
    if recording.size == 0:
        return recording
    np.nan_to_num(recording, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
    frame_size = max(1, SAMPLE_RATE // 50)
    frame_count = recording.size // frame_size
    if frame_count == 0:
        return recording
    frames = recording[: frame_count * frame_size].reshape(frame_count, frame_size)
    frame_rms = np.sqrt(np.mean(frames * frames, axis=1))
    noise_floor = float(np.percentile(frame_rms, 20))
    activity_threshold = max(AUTO_GAIN_ACTIVITY_THRESHOLD, noise_floor * 1.8)
    active_rms = frame_rms[frame_rms >= activity_threshold]
    if active_rms.size == 0:
        active_rms = frame_rms[frame_rms >= AUTO_GAIN_ACTIVITY_THRESHOLD]
        if active_rms.size == 0:
            return recording
    speech_rms = float(np.percentile(active_rms, 60))
    if speech_rms <= 0.0 or speech_rms >= AUTO_GAIN_TARGET_RMS:
        return recording
    gain = min(AUTO_GAIN_MAX, AUTO_GAIN_TARGET_RMS / speech_rms)
    peak = float(max(np.max(recording), -np.min(recording)))
    if peak > 0.0:
        gain = min(gain, AUTO_GAIN_PEAK_CEILING / peak)
    if gain > 1.0:
        np.multiply(recording, gain, out=recording)
    return recording


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

    def test_matches_original_float32_samples_bit_for_bit(self):
        rng = np.random.default_rng(20261002)
        for sample_count in (0, 1, 319, 320, 321, 639, 640, 641, 8000, 16013, 80000):
            quiet = rng.normal(0.0, 0.01, sample_count).astype(np.float32)
            profiles = {
                "quiet": quiet,
                "loud": quiet * np.float32(30.0),
                "silence": np.zeros(sample_count, dtype=np.float32),
                "signed_zero": np.full(sample_count, -0.0, dtype=np.float32),
                "subnormal": np.full(
                    sample_count,
                    np.nextafter(np.float32(0.0), np.float32(1.0)),
                    dtype=np.float32,
                ),
            }
            invalid = quiet.copy()
            for index, value in enumerate((np.nan, np.inf, -np.inf)):
                if index < sample_count:
                    invalid[index] = value
            profiles["invalid"] = invalid
            if sample_count:
                outlier = quiet.copy()
                outlier[-1] = np.float32(0.9)
                profiles["tail_peak"] = outlier
            for profile, samples in profiles.items():
                with self.subTest(samples=sample_count, profile=profile):
                    expected = samples.copy()
                    actual = samples.copy()
                    _gain_before_finite_fast_path(expected)
                    self.assertIs(apply_automatic_gain(actual), actual)
                    np.testing.assert_array_equal(
                        actual.view(np.uint32), expected.view(np.uint32)
                    )

    def test_invalid_samples_are_zeroed_even_without_a_complete_frame(self):
        recording = np.array([np.nan, np.inf, -np.inf, -0.0, 0.01], dtype=np.float32)
        expected = np.array([0.0, 0.0, 0.0, -0.0, 0.01], dtype=np.float32)

        self.assertIs(apply_automatic_gain(recording), recording)

        np.testing.assert_array_equal(recording.view(np.uint32), expected.view(np.uint32))

    def test_finite_fast_path_uses_only_a_boolean_sanitization_mask(self):
        recording = np.full(8000, 0.01, dtype=np.float32)
        masks = []
        isfinite = np.isfinite

        def track_mask(samples):
            mask = isfinite(samples)
            masks.append(mask)
            return mask

        with mock.patch.object(audio.np, "isfinite", side_effect=track_mask), mock.patch.object(
            audio.np, "nan_to_num", side_effect=AssertionError("finite input was sanitized")
        ):
            apply_automatic_gain(recording)

        self.assertEqual(len(masks), 1)
        self.assertEqual(masks[0].dtype, np.dtype(bool))
        self.assertEqual(masks[0].nbytes, recording.size)

    def test_invalid_fallback_sanitizes_the_original_array_in_place(self):
        recording = np.full(8000, 0.01, dtype=np.float32)
        recording[:3] = [np.nan, np.inf, -np.inf]

        with mock.patch.object(audio.np, "nan_to_num", wraps=np.nan_to_num) as sanitize:
            apply_automatic_gain(recording)

        self.assertEqual(sanitize.call_count, 1)
        self.assertIs(sanitize.call_args.args[0], recording)
        self.assertEqual(
            sanitize.call_args.kwargs,
            {"copy": False, "nan": 0.0, "posinf": 0.0, "neginf": 0.0},
        )
        np.testing.assert_array_equal(recording[:3].view(np.uint32), np.zeros(3, np.uint32))

    def test_amplification_keeps_the_original_multiply_and_output_buffer(self):
        recording = np.full(8000, 0.01, dtype=np.float32)
        expected = recording.copy()
        _gain_before_finite_fast_path(expected)

        with mock.patch.object(audio.np, "multiply", wraps=np.multiply) as multiply:
            self.assertIs(apply_automatic_gain(recording), recording)

        self.assertEqual(multiply.call_count, 1)
        self.assertIs(multiply.call_args.args[0], recording)
        self.assertEqual(multiply.call_args.args[1], AUTO_GAIN_MAX)
        self.assertIs(multiply.call_args.kwargs["out"], recording)
        np.testing.assert_array_equal(recording.view(np.uint32), expected.view(np.uint32))

    def test_incomplete_frame_is_ignored_for_rms_but_limits_and_receives_gain(self):
        recording = np.full(321, 0.01, dtype=np.float32)
        recording[-1] = np.float32(0.9)
        expected = recording.copy()
        gain = AUTO_GAIN_PEAK_CEILING / float(recording[-1])
        np.multiply(expected, gain, out=expected)

        apply_automatic_gain(recording)

        np.testing.assert_array_equal(recording.view(np.uint32), expected.view(np.uint32))

    def test_gain_preserves_noncontiguous_views_and_their_unused_samples(self):
        rng = np.random.default_rng(20261002)
        original = rng.normal(0.0, 0.01, 16002).astype(np.float32)
        original[10] = np.nan
        original[16] = np.inf
        for selector in (slice(None, None, 2), slice(None, None, -1)):
            with self.subTest(stride=selector.step):
                expected_base = original.copy()
                actual_base = original.copy()
                expected = expected_base[selector]
                actual = actual_base[selector]

                _gain_before_finite_fast_path(expected)
                self.assertIs(apply_automatic_gain(actual), actual)

                np.testing.assert_array_equal(
                    actual_base.view(np.uint32), expected_base.view(np.uint32)
                )

    def test_read_only_float32_rejection_is_unchanged(self):
        for sample_count in (1, 319, 320, 8000):
            for value in (0.0, 0.01, np.nan):
                with self.subTest(samples=sample_count, value=value):
                    recording = np.full(sample_count, value, dtype=np.float32)
                    recording.flags.writeable = False
                    with self.assertRaisesRegex(ValueError, "read-only"):
                        _gain_before_finite_fast_path(recording)
                    with self.assertRaisesRegex(ValueError, "read-only"):
                        apply_automatic_gain(recording)

        empty = np.zeros(0, dtype=np.float32)
        empty.flags.writeable = False
        self.assertIs(apply_automatic_gain(empty), empty)

    def test_gain_on_recording_copy_does_not_change_raw_meter_input(self):
        raw_block = np.full((8000, 1), 0.01, dtype=np.float32)
        original = raw_block.copy()
        raw_level = calculate_volume(raw_block)
        recording = raw_block[:, 0].copy()

        apply_automatic_gain(recording)

        np.testing.assert_array_equal(raw_block.view(np.uint32), original.view(np.uint32))
        self.assertEqual(calculate_volume(raw_block), raw_level)
        self.assertGreater(calculate_volume(recording), raw_level)

    def test_non_inexact_inputs_keep_the_original_sanitizer_behavior(self):
        for dtype in (np.int16, np.bool_, object, "U4"):
            with self.subTest(dtype=dtype):
                recording = np.array([0.0, 0.01], dtype=dtype)
                expected = recording.copy()
                _gain_before_finite_fast_path(expected)
                with mock.patch.object(
                    audio.np, "isfinite", side_effect=AssertionError("non-inexact input was scanned")
                ), mock.patch.object(audio.np, "nan_to_num", wraps=np.nan_to_num) as sanitize:
                    self.assertIs(apply_automatic_gain(recording), recording)

                self.assertEqual(sanitize.call_count, 1)
                np.testing.assert_array_equal(recording, expected)


if __name__ == "__main__":
    unittest.main()
