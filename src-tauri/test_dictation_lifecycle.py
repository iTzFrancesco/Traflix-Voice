from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from whisper_engine import transcriber
from whisper_engine.constants import BLOCK_SIZE, SAMPLE_RATE


def local_engine():
    from whisper_engine.engine import WhisperEngine
    from whisper_engine.parakeet import ParakeetRecognizer

    engine = WhisperEngine()
    native = MagicMock()
    native.create_stream.return_value.result.text = "synthetic transcript"
    engine.model = ParakeetRecognizer(native)
    engine.current_model_size = "parakeet"
    events = []
    engine.log = events.append
    return engine, native, events


def test_unload_between_local_preprocessing_and_native_decode_preserves_result():
    engine, native, events = local_engine()
    prepare = transcriber._prepare_local_recording

    def unload_before_decode(recording):
        engine.unload_model()
        return prepare(recording)

    try:
        with patch.object(transcriber, "_prepare_local_recording", unload_before_decode):
            engine._process_recording(
                np.full(SAMPLE_RATE, 0.1, dtype=np.float32),
                "parakeet", "it", 1.0, "local",
            )
        results = [event for event in events if event["status"] == "result"]
        assert len(results) == 1, events
        assert results[0]["text"] == "synthetic transcript"
        assert engine.model is None
        assert native.decode_stream.call_count == 1
    finally:
        engine.close_transcription_worker()


def test_shutdown_during_local_native_decode_suppresses_late_result():
    engine, native, events = local_engine()
    native.decode_stream.side_effect = lambda _stream: setattr(engine, "_shutting_down", True)
    try:
        engine._process_recording(
            np.full(SAMPLE_RATE, 0.1, dtype=np.float32),
            "parakeet", "it", 1.0, "local",
        )
        assert not any(event["status"] == "result" for event in events), events
        assert native.decode_stream.call_count == 1
    finally:
        engine.close_transcription_worker()


@pytest.mark.parametrize("initial_enabled, changed_enabled", [(False, True), (True, False)])
def test_cloud_capture_preserves_snapshotted_options(initial_enabled, changed_enabled):
    from whisper_engine import engine as engine_module
    from whisper_engine.engine import WhisperEngine

    engine = WhisperEngine()
    engine.provider = "cloud"
    engine.cloud_correct_uncertain = initial_enabled
    engine.cloud_vocabulary = "initial synthetic vocabulary" if initial_enabled else ""
    engine.cloud_speech_filter = initial_enabled
    engine.log = lambda event: on_listening(event)

    def on_listening(event):
        if event["status"] == "listening":
            engine.cloud_correct_uncertain = changed_enabled
            engine.cloud_vocabulary = "new synthetic vocabulary" if changed_enabled else ""
            engine.cloud_speech_filter = changed_enabled
            engine.stop_recording()

    class InputStream:
        def __init__(self, **kwargs):
            self.callback = kwargs["callback"]

        def __enter__(self):
            self.callback(np.full((BLOCK_SIZE, 1), 0.1, dtype=np.float32), BLOCK_SIZE, None, None)
            return self

        def __exit__(self, *_args):
            return False

    try:
        with patch.object(engine_module.sd, "InputStream", InputStream), \
             patch.object(transcriber, "prewarm_groq_connection"), \
             patch.object(transcriber, "transcribe_cloud") as cloud:
            engine.start_transcription(None, "parakeet").result(timeout=2)
            engine._transcription_executor.submit(lambda: None).result(timeout=2)
            cloud.assert_called_once()
            assert cloud.call_args.kwargs["correct_uncertain"] is initial_enabled
            assert cloud.call_args.kwargs["vocabulary"] == (
                "initial synthetic vocabulary" if initial_enabled else ""
            )
            assert cloud.call_args.kwargs["speech_filter"] is initial_enabled
    finally:
        engine.close_transcription_worker()


def test_provider_change_during_local_capture_preserves_captured_model():
    from whisper_engine import engine as engine_module

    engine, native, events = local_engine()

    def log(event):
        events.append(event)
        if event["status"] == "listening":
            engine.provider = "cloud"
            engine.unload_model()
            engine.stop_recording()

    engine.log = log

    class InputStream:
        def __init__(self, **kwargs):
            self.callback = kwargs["callback"]

        def __enter__(self):
            self.callback(np.full((BLOCK_SIZE, 1), 0.1, dtype=np.float32), BLOCK_SIZE, None, None)
            return self

        def __exit__(self, *_args):
            return False

    try:
        with patch.object(engine_module.sd, "InputStream", InputStream):
            engine.start_transcription(None, "parakeet").result(timeout=2)
            engine._transcription_executor.submit(lambda: None).result(timeout=2)
        results = [event for event in events if event["status"] == "result"]
        assert len(results) == 1, events
        assert results[0]["provider"] == "local"
        assert results[0]["duration"] == BLOCK_SIZE / SAMPLE_RATE
        assert results[0]["text"] == "synthetic transcript"
        assert native.decode_stream.call_count == 1
    finally:
        engine.close_transcription_worker()


def test_queued_local_transcription_keeps_model_after_unload():
    from whisper_engine import engine as engine_module

    engine, native, events = local_engine()
    worker_started, release_worker = engine_module.threading.Event(), engine_module.threading.Event()
    blocker = engine._transcription_executor.submit(
        lambda: (worker_started.set(), release_worker.wait(timeout=3))
    )
    assert worker_started.wait(timeout=1)

    def log(event):
        events.append(event)
        if event["status"] == "listening":
            engine.stop_recording()

    engine.log = log

    class InputStream:
        def __init__(self, **kwargs):
            self.callback = kwargs["callback"]

        def __enter__(self):
            self.callback(np.full((BLOCK_SIZE, 1), 0.1, dtype=np.float32), BLOCK_SIZE, None, None)
            return self

        def __exit__(self, *_args):
            return False

    try:
        with patch.object(engine_module.sd, "InputStream", InputStream):
            engine.start_transcription(None, "parakeet").result(timeout=2)
        assert not any(event["status"] == "result" for event in events)
        assert engine.unload_model()
        release_worker.set()
        blocker.result(timeout=1)
        engine._transcription_executor.submit(lambda: None).result(timeout=2)
        results = [event for event in events if event["status"] == "result"]
        assert len(results) == 1, events
        assert results[0]["text"] == "synthetic transcript"
        assert native.decode_stream.call_count == 1
    finally:
        release_worker.set()
        engine.close_transcription_worker()


def test_shutdown_during_silent_local_processing_does_not_emit_result():
    engine, _native, events = local_engine()
    prepare = transcriber._prepare_local_recording

    def shutdown_and_prepare_silence(recording):
        engine._shutting_down = True
        return prepare(np.zeros_like(recording))

    try:
        with patch.object(transcriber, "_prepare_local_recording", shutdown_and_prepare_silence):
            engine._process_recording(
                np.full(SAMPLE_RATE, 0.1, dtype=np.float32),
                "parakeet", "it", 1.0, "local",
            )
        assert not any(event["status"] == "result" for event in events), events
    finally:
        engine.close_transcription_worker()
