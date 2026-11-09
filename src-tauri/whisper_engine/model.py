"""Local Parakeet Ultra dispatch through the native GGUF CPU/GPU runtime."""
from whisper_engine import parakeet as parakeet_backend
from whisper_engine.native_parakeet import NativeRecognizer


def is_backend_available():
    return parakeet_backend.is_backend_available()


def backend_status():
    return parakeet_backend.backend_status()


def normalize_model_id(size):
    return parakeet_backend.normalize_model_id(size)


def release_model(model):
    """Best-effort native release for a loaded adapter (see ParakeetRecognizer.close)."""
    if model is None:
        return
    try:
        close = getattr(model, "close", None) or getattr(model, "release", None)
        if callable(close):
            close()
    except Exception:
        pass


def retain_model(model):
    """Pin the native handle for a capture or inference already in progress."""
    model_types = (
        parakeet_backend.AdaptiveRecognizer,
        parakeet_backend.ParakeetRecognizer,
        NativeRecognizer,
    )
    return model.snapshot() if isinstance(model, model_types) else model


def verify_model(models_dir, size):
    normalize_model_id(size)
    return parakeet_backend.verify(models_dir)


def load_model(models_dir, size, log_func):
    size = normalize_model_id(size)
    return parakeet_backend.load(models_dir, log_func)


def preload_default_model(models_dir, model_size, log_func):
    try:
        model_size = normalize_model_id(model_size)
        is_valid, _ = verify_model(models_dir, model_size)
        if is_valid:
            log_func({"status": "loading_model", "message": f"Caricamento modello {model_size}..."})
            m = load_model(models_dir, model_size, log_func)
            log_func({"status": "ready", "message": "Modello pronto."})
            return m, model_size
        else:
            log_func({"status": "ready", "message": "Pronto (nessun modello da precaricare)."})
            return None, None
    except Exception as e:
        log_func({"status": "ready", "message": f"Pronto (precaricamento saltato: {str(e)})"})
        return None, None


def download_model(models_dir, size, log_func):
    try:
        normalize_model_id(size)
    except ValueError as error:
        log_func({"status": "download_error", "message": str(error)})
        return
    parakeet_backend.download(models_dir, log_func)
