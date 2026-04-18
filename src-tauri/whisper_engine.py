import sys
import json
import sounddevice as sd
import numpy as np
import os
from faster_whisper import WhisperModel
from huggingface_hub import snapshot_download
import queue
import threading
import concurrent.futures
import shutil

# Configurazione standard audio
SAMPLE_RATE = 16000
BLOCK_SIZE = 4000  # 250ms per blocco
TRANSCRIPTION_TIMEOUT = 60  # seconds

class WhisperEngine:
    def __init__(self):
        self.model = None
        self.current_model_size = None
        self.current_device = "cpu"
        self.audio_queue = queue.Queue()
        self.is_recording = False
        self.models_dir = None
        self.compute_device = "cpu"  # "cpu", "cuda", "auto"

    def _resolve_device(self):
        """Resolve the actual device to use based on compute_device preference."""
        if self.compute_device == "cpu":
            return "cpu", "int8"

        cuda_available = False
        device_name = "N/A"
        try:
            import torch
            cuda_available = torch.cuda.is_available()
            if cuda_available:
                device_name = torch.cuda.get_device_name(0)
        except ImportError:
            cuda_available = False
        except Exception:
            cuda_available = False

        if self.compute_device == "cuda":
            if cuda_available:
                return "cuda", "float16"
            else:
                self.log({"status": "error", "message": "CUDA richiesto ma non disponibile. Verifica driver GPU e installazione PyTorch con CUDA."})
                self.log({"status": "info", "message": "Fallback su CPU."})
                return "cpu", "int8"

        # "auto": try CUDA first, fall back to CPU
        if cuda_available:
            self.log({"status": "info", "message": f"GPU rilevata: {device_name}. Uso CUDA."})
            return "cuda", "float16"
        else:
            self.log({"status": "info", "message": "Nessuna GPU CUDA disponibile. Uso CPU."})
            return "cpu", "int8"

    def check_gpu(self):
        """Check GPU availability and report back."""
        cuda_available = False
        device_name = "N/A"
        try:
            import torch
            cuda_available = torch.cuda.is_available()
            if cuda_available:
                device_name = torch.cuda.get_device_name(0)
        except ImportError:
            pass
        except Exception:
            pass

        self.log({
            "status": "gpu_info",
            "cuda_available": cuda_available,
            "device_name": device_name,
            "current_device": self.current_device
        })

    def verify_model(self, size):
        """Verify that a downloaded model is valid and complete."""
        model_dir = os.path.join(self.models_dir, f"faster-whisper-{size}")

        # Check if directory exists
        if not os.path.exists(model_dir):
            return False, f"Model directory does not exist: {model_dir}"

        # Check for essential model.bin file
        model_bin = os.path.join(model_dir, "model.bin")
        if not os.path.exists(model_bin):
            return False, f"Essential file model.bin not found in {model_dir}"

        # Verify model.bin has non-zero size
        try:
            size_bytes = os.path.getsize(model_bin)
            if size_bytes == 0:
                return False, f"model.bin exists but has zero size"
        except OSError as e:
            return False, f"Cannot read model.bin: {str(e)}"

        # Check for other important files and verify they're non-zero
        important_files = ["config.json", "vocabulary.json", "tokenizer.json"]
        for filename in important_files:
            filepath = os.path.join(model_dir, filename)
            if os.path.exists(filepath):
                try:
                    file_size = os.path.getsize(filepath)
                    if file_size == 0:
                        return False, f"{filename} exists but has zero size"
                except OSError as e:
                    return False, f"Cannot read {filename}: {str(e)}"

        return True, "Model verified successfully"

    def load_model(self, size, device=None):
        if device is not None:
            self.compute_device = device

        resolved_device, compute_type = self._resolve_device()
        needs_reload = (
            self.model is None
            or self.current_model_size != size
            or self.current_device != resolved_device
        )

        if needs_reload:
            # Verify model before attempting to load
            is_valid, message = self.verify_model(size)
            if not is_valid:
                error_msg = f"Model verification failed: {message}. Please re-download the model."
                self.log({"status": "error", "message": error_msg})
                raise Exception(error_msg)

            self.log({"status": "info", "message": f"Caricamento modello {size} su {resolved_device}..."})
            download_root = os.path.join(self.models_dir, f"faster-whisper-{size}")
            try:
                self.model = WhisperModel(download_root, device=resolved_device, compute_type=compute_type)
                self.current_device = resolved_device
            except Exception as e:
                if resolved_device == "cuda":
                    self.log({"status": "error", "message": f"Errore inizializzazione CUDA: {str(e)}. Fallback su CPU."})
                    self.model = WhisperModel(download_root, device="cpu", compute_type="int8")
                    self.current_device = "cpu"
                else:
                    raise
            self.current_model_size = size
            self.log({"status": "info", "message": f"Modello caricato con successo su {self.current_device}."})

    def _preload_default_model(self, model_size="small"):
        """Pre-load the selected model at startup so first transcription is instant."""
        try:
            is_valid, _ = self.verify_model(model_size)
            if is_valid:
                self.log({"status": "info", "message": f"Pre-caricamento modello {model_size}..."})
                self.load_model(model_size)
                self.log({"status": "info", "message": f"Modello {model_size} pronto."})
            else:
                self.log({"status": "info", "message": f"Modello {model_size} non scaricato, preload saltato."})
        except Exception as e:
            self.log({"status": "info", "message": f"Pre-caricamento saltato: {str(e)}"})

    def log(self, data):
        print(json.dumps(data))
        sys.stdout.flush()

    def download_model(self, size):
        local_dir = os.path.join(self.models_dir, f"faster-whisper-{size}")

        try:
            self.log({"status": "downloading", "message": f"Inizio download modello {size}...", "model": size})

            # Download the model
            snapshot_download(
                repo_id=f"Systran/faster-whisper-{size}",
                local_dir=local_dir,
                local_dir_use_symlinks=False
            )

            # Verify the downloaded model
            is_valid, message = self.verify_model(size)
            if not is_valid:
                # Model verification failed - clean up incomplete download
                self.log({"status": "error", "message": f"Model verification failed: {message}"})

                try:
                    if os.path.exists(local_dir):
                        shutil.rmtree(local_dir)
                        self.log({"status": "info", "message": "Incomplete download removed."})
                except Exception as cleanup_error:
                    self.log({"status": "error", "message": f"Failed to clean up incomplete download: {str(cleanup_error)}"})

                self.log({"status": "error", "message": f"Download incomplete or corrupted. Please try again."})
                return

            self.log({"status": "download_complete", "message": f"Modello {size} scaricato e verificato correttamente.", "model": size})

        except ConnectionError as e:
            self.log({"status": "error", "message": f"Network error during download: {str(e)}. Check your internet connection and try again."})
            # Clean up partial download
            try:
                if os.path.exists(local_dir):
                    shutil.rmtree(local_dir)
            except Exception:
                pass

        except OSError as e:
            self.log({"status": "error", "message": f"Disk error during download: {str(e)}. Check available disk space and permissions."})
            # Clean up partial download
            try:
                if os.path.exists(local_dir):
                    shutil.rmtree(local_dir)
            except Exception:
                pass

        except Exception as e:
            self.log({"status": "error", "message": f"Download failed: {str(e)}. Please try again."})
            # Clean up partial download
            try:
                if os.path.exists(local_dir):
                    shutil.rmtree(local_dir)
            except Exception:
                pass

    def audio_callback(self, indata, frames, time, status):
        if status:
            self.log({"status": "warning", "message": str(status)})
        
        # Inserisci in coda per trascrizione
        self.audio_queue.put(indata.copy())
        
        # Calcola volume (RMS) per UI
        if self.is_recording:
            volume_norm = np.linalg.norm(indata) * 10
            # Mappa a circa 0-100
            level = min(100, int(volume_norm))
            # Log throttled (sounddevice chiama molto spesso, noi limitiamo)
            if not hasattr(self, '_last_vol_time'): self._last_vol_time = 0
            import time as pytime
            current_time = pytime.time()
            if current_time - self._last_vol_time > 0.05: # 20fps
                self.log({"status": "volume", "value": level})
                self._last_vol_time = current_time

    def transcribe(self, device_id, model_size, language="it"):
        try:
            self.load_model(model_size)
            
            self.is_recording = True
            self.audio_queue = queue.Queue()
            audio_data = []

            self.log({"status": "listening", "message": "In ascolto... parla ora."})

            import time as pytime
            start_time = pytime.time()

            with sd.InputStream(device=device_id, channels=1, callback=self.audio_callback,
                                samplerate=SAMPLE_RATE, blocksize=BLOCK_SIZE):
                while self.is_recording:
                    try:
                        data = self.audio_queue.get(timeout=0.1)
                        audio_data.append(data)
                    except queue.Empty:
                        continue

            recording_duration = pytime.time() - start_time

            self.log({"status": "processing", "message": "Trascrizione in corso..."})
            
            if not audio_data:
                self.log({"status": "ready", "message": "Nessun audio catturato."})
                return

            recording = np.concatenate(audio_data, axis=0).flatten().astype(np.float32)

            lang_param = None if language == "auto" else language

            def _run_inference():
                # beam_size=5 balances transcription accuracy vs latency for
                # real-time dictation; higher values (e.g. 10) improve quality
                # marginally but double decode time on CPU, while lower values
                # (1-2) noticeably degrade Italian accuracy on longer utterances.
                segments, info = self.model.transcribe(recording, beam_size=5, language=lang_param)
                text = " ".join([segment.text for segment in segments]).strip()
                return text, info

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_run_inference)
                try:
                    text, info = future.result(timeout=TRANSCRIPTION_TIMEOUT)
                except concurrent.futures.TimeoutError:
                    self.log({"status": "error", "message": f"Transcription timeout after {TRANSCRIPTION_TIMEOUT} seconds"})
                    self.log({"status": "ready", "message": "Motore Whisper pronto."})
                    return

            result = {"status": "result", "text": text, "duration": recording_duration}
            if language == "auto" and hasattr(info, "language"):
                result["detected_language"] = info.language
            self.log(result)

        except Exception as e:
            self.log({"status": "error", "message": str(e)})

    def run(self):
        self.log({"status": "ready", "message": "Motore Whisper pronto."})
        for line in sys.stdin:
            try:
                data = json.loads(line)
                cmd = data.get("command")
                
                if cmd == "init":
                    self.models_dir = data.get("models_dir")
                    if data.get("compute_device"):
                        self.compute_device = data.get("compute_device")
                    self.log({"status": "info", "message": f"Cartella modelli impostata: {self.models_dir}"})
                    self.check_gpu()
                    preload_model = data.get("model", "small")
                    threading.Thread(target=self._preload_default_model, args=(preload_model,), daemon=True).start()
                elif cmd == "download":
                    threading.Thread(target=self.download_model, args=(data.get("model"),)).start()
                elif cmd == "check_gpu":
                    self.check_gpu()
                elif cmd == "set_device":
                    new_device = data.get("device", "cpu")
                    if new_device in ("cpu", "cuda", "auto"):
                        self.compute_device = new_device
                        self.log({"status": "info", "message": f"Dispositivo di calcolo impostato: {new_device}"})
                        # Force model reload on next transcription
                        self.current_device = None
                        self.check_gpu()
                    else:
                        self.log({"status": "error", "message": f"Dispositivo non valido: {new_device}"})
                elif cmd == "transcribe":
                    # Eseguiamo in un thread per non bloccare stdin
                    threading.Thread(target=self.transcribe,
                                     args=(data.get("device"), data.get("model", "small"), data.get("language", "it"))).start()
                elif cmd == "stop":
                    self.is_recording = False
                elif cmd == "quit":
                    break
            except Exception as e:
                self.log({"status": "error", "message": str(e)})

if __name__ == "__main__":
    engine = WhisperEngine()
    engine.run()
