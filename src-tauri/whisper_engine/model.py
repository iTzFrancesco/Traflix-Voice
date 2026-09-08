import os
from pywhispercpp.model import Model
from huggingface_hub import hf_hub_download

from whisper_engine import parakeet as parakeet_backend


def inference_threads():
    try:
        count = os.cpu_count() or 1
    except Exception:
        count = 1
    # The large-v3 encoder scales up to ~8 threads on a desktop CPU (R10-R11:
    # -31% vs the default 4). Transcription is bursty, so using more cores
    # briefly is preferable to a slower response on every dictation.
    return max(1, min(8, count))


def verify_model(models_dir, size):
    if parakeet_backend.is_parakeet_model(size):
        return parakeet_backend.verify(models_dir)
    model_path = os.path.join(models_dir, f"ggml-{size}.bin")
    if not os.path.exists(model_path):
        return False, f"File non trovato: {model_path}"
    try:
        if os.path.getsize(model_path) == 0:
            return False, f"File vuoto: {model_path}"
    except OSError as e:
        return False, str(e)
    return True, "OK"


def load_model(models_dir, size, log_func):
    if parakeet_backend.is_parakeet_model(size):
        return parakeet_backend.load(models_dir, log_func)
    is_valid, msg = verify_model(models_dir, size)
    if not is_valid:
        log_func({"status": "error", "message": f"Modello {size} non valido: {msg}"})
        raise Exception(f"Modello {size} non valido: {msg}")

    log_func({"status": "loading_model", "message": f"Caricamento modello {size}..."})
    model_path = os.path.join(models_dir, f"ggml-{size}.bin")
    try:
        m = Model(model_path, print_realtime=False, print_progress=False,
                  n_threads=inference_threads())
        log_func({"status": "info", "message": f"Modello {size} caricato."})
        return m
    except Exception as e:
        log_func({"status": "error", "message": f"Errore caricamento modello: {str(e)}"})
        raise


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
    if parakeet_backend.is_parakeet_model(size):
        parakeet_backend.download(models_dir, log_func)
        return

    local_path = os.path.join(models_dir, f"ggml-{size}.bin")

    try:
        log_func({"status": "downloading", "message": f"Download modello {size}...", "model": size})
        hf_hub_download(
            repo_id="ggerganov/whisper.cpp",
            filename=f"ggml-{size}.bin",
            local_dir=models_dir,
            local_dir_use_symlinks=False
        )

        is_valid, msg = verify_model(models_dir, size)
        if not is_valid:
            log_func({"status": "error", "message": f"Verifica fallita: {msg}"})
            try:
                if os.path.exists(local_path):
                    os.remove(local_path)
            except Exception:
                pass
            return

        log_func({"status": "download_complete", "message": f"Modello {size} scaricato.", "model": size})
    except Exception as e:
        log_func({"status": "download_error", "message": f"Download fallito: {str(e)}", "model": size})
        try:
            if os.path.exists(local_path):
                os.remove(local_path)
        except Exception:
            pass
