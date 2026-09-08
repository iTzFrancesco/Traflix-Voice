# Report modelli STT — Traflix Voice (settembre 2026)

Vincoli: i5-11600K, 16 GB RAM, RX 6500XT. Nota chiave: su Windows la 6500XT è
inutilizzabile per l'inferenza (niente CUDA/ROCm) → il locale gira su **CPU**.
Oggi: locale = Whisper via `pywhispercpp` (ggml da `ggerganov/whisper.cpp`);
cloud = Groq `whisper-large-v3-turbo`.

## Locali

| Modello | Peso | Qualità IT | Velocità su i5 | Sforzo integrazione |
|---|---|---|---|---|
| ⭐ **Whisper Large V3 Turbo** (`ggml-large-v3-turbo.bin`) | ~1,6 GB (q5_0 ~600 MB, q8_0 ~850 MB) | Ottima (~large-v3) | ~8× large-v3, dettati brevi in 1–3 s | **Zero**: stesso stack, basta l'ID nel catalogo |
| Whisper Large V3 q5_0 | ~1,1 GB | Max famiglia Whisper | Lento su CPU | Zero, ma sconsigliato (turbo ≈ pari qualità, molto più veloce) |
| ⭐ **Parakeet TDT 0.6B v3** (NVIDIA) | ~600–700 MB (int8) | Ottima (FLEURS IT WER 3,0%) | Altissima (encoder non-autoregressivo) | **Medio**: nuovo backend `sherpa-onnx` (wheel Windows con onnxruntime, niente torch) |
| Faster-Whisper `large-v3-turbo` int8 | ~800 MB | = turbo | Su CPU spesso > whisper.cpp | Medio-basso: cambio backend, `pip install faster-whisper` |
| ❌ Distil Large v3 / v3.5 | ~1,5 GB | **Solo inglese** | Veloce | Scartato come default (ok solo dettatura EN) |
| ❌ Moonshine / Voxtral 3B+ | — | EN-only / pesante | — | Scartati (CPU insufficiente) |

## Cloud (solo piani gratis)

| Provider / modello | Free tier (verificato) | Sforzo |
|---|---|---|
| ⭐ **Groq `whisper-large-v3-turbo`** (attuale) | **Attivo, non deprecato**: 7.200 audio-sec/ora (~2 h/ora), 28.800/giorno (~8 h/giorno) | Zero: tenere così |
| **Google Gemini API** (AI Studio, chiave gratuita) | Free tier esistente e generoso; audio nativo, ottimo IT + punteggiatura | Medio: nuovo client (API diversa) — miglior 2° provider |
| Azure Speech piano F0 | 5 ore/mese gratis perpetue | Medio: SDK diverso — buon fallback |
| HuggingFace Inference Providers | Free limitato, turbo disponibile, possibili cold start | Basso: API OpenAI-compatible — riserva |
| ❌ OpenAI / Deepgram / AssemblyAI / ElevenLabs / Voxtral API | Pagamento o solo crediti trial | Scartati |

## Cosa fare

1. **Subito (locale)**: `large-v3-turbo` (o `large-v3-turbo-q8_0` se RAM contesa) come
   nuovo default al posto di small/large-v3. È già scaricabile dal repo whisper.cpp
   usato da `download_model` — basta aggiungere gli ID a `WHISPER_MODELS`.
2. **Subito (cloud)**: nessuna urgenza — Groq turbo resta gratis, generoso e attuale.
3. **Medio termine**: Parakeet v3 via `sherpa-onnx` come modalità "veloce" locale;
   Gemini free come secondo provider cloud.

Fonti: API Hugging Face (repo `ggerganov/whisper.cpp`, `nvidia/parakeet-tdt-0.6b-v3`,
`csukuangfj/sherpa-onnx-*`, `Systran/faster-whisper-large-v3`), docs Groq
(models/rate-limits/speech-to-text), docs Google AI Studio rate-limits — sett. 2026.
