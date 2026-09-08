"""Local model backend (Parakeet-only).

The whisper.cpp path was removed: on CPU-only hardware Parakeet decodes ~30x
faster at equal transcription quality (docs/local-optimization-report.md).
Model ids from older settings are accepted and resolve to Parakeet instead of
failing, so existing installs keep working after the switch.
"""
from whisper_engine import parakeet as parakeet_backend


def verify_model(models_dir, size):
    return parakeet_backend.verify(models_dir)


def load_model(models_dir, size, log_func):
    if not parakeet_backend.is_parakeet_model(size):
        log_func({"status": "info", "message": f"Modello locale '{size}' non supportato, uso Parakeet."})
    return parakeet_backend.load(models_dir, log_func)


def preload_default_model(models_dir, model_size, log_func):
    try:
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
    parakeet_backend.download(models_dir, log_func)
