# Traflix Voice — valutazione modelli ASR alternativi a whisper-large-v3-turbo

Data: 2026-08-17
Stato: ricerca, nessuna modifica al codice.

## Contesto

L'app usa oggi `whisper-large-v3-turbo` via API Groq (`src-tauri/whisper_engine/constants.py:6`),
con free tier permissivo (limiti: 28.800 s/giorno, 7.200 s/ora) e latenza end-to-end
reale ~180–190 ms di mediana (vedi `docs/latency-optimization-report.md`). La dettatura è
in **italiano**. Vincoli dell'utente: non perdere velocità (o guadagno di precisione che
giustifichi la perdita), modelli recenti (2025–2026), gratuiti o con free tier permissivo.

## Domanda chiave: cosa offre Groq oggi?

**Nessun modello ASR nuovo è stato aggiunto a Groq.** Il catalogo resta limitato a Whisper:

| Modello Groq | Lingue | WER | Velocità real-time | Prezzo |
|---|---|---|---|---|
| `whisper-large-v3-turbo` (in uso) | multilingue | ~12% | 216× | $0.04/ora |
| `whisper-large-v3` | multilingue | ~10,3% | 189× | $0.111/ora |
| `distil-whisper-large-v3-en` | solo inglese | ~13% | 262× | $0.02/ora |

Fonte: https://console.groq.com/docs/speech-to-text

Conseguenza: **qualunque sostituzione con un modello più nuovo implica cambiare provider
o passare a inferenza locale.** Non esiste oggi un'alternativa "più recente" disponibile
sullo stesso endpoint Groq.

## Candidati nuovi (2025–2026)

### 1. NVIDIA Parakeet TDT 0.6B v3
- 600M parametri, **25 lingue europee incluso l'italiano (it)**, rilevamento automatico della lingua.
- Licenza **CC BY 4.0** (permissiva), pesi open su HuggingFace. Rilasciato ago 2025.
- Punteggiatura/maiuscole automatiche, timestamp word-level. NON è streaming, NON traduce.
- Velocità: RTF <0.1× su CPU, ~50–150 ms per una clip da 2 s. Nei benchmark di `parakeet.cpp`
  è ~12× più veloce di whisper.cpp large-v3-turbo su GPU a parità di accuratezza.
- Limite noto (card ufficiale): fragile su vocaboli fuori vocabolario, frasi incomplete/parola-per-parola.
- Runtime locale: **non gira in whisper.cpp/pywhispercpp**. Servono `transcribe.cpp`
  (progetto Mozilla.ai, annunciato giu 2026, runtime GGUF/ggml con bindings Python/Rust/C),
  `parakeet.cpp` (mudler), oppure NeMo. NIM hosted su build.nvidia.com.

Fonti: https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3 · https://github.com/mudler/parakeet.cpp · https://blog.mozilla.ai/announcing-transcribe-cpp/

### 2. Qwen3-ASR (Alibaba) — il candidato più recente
- Famiglia rilasciata **gen 2026**: `Qwen3-ASR-1.7B` e `Qwen3-ASR-0.6B` + `Qwen3-ForcedAligner-0.6B`.
- **Apache 2.0** (open source), addestrati su Qwen3-Omni.
- 30 lingue + 22 dialetti cinesi, **incluso l'italiano (it)**; rilevamento lingua migliore di Whisper-large-v3.
- Modalità **offline e streaming**. Supporto nativo Transformers dal giu 2026 (`torch.compile`).
- Il paper dichiara: 1.7B = **stato dell'arte tra gli ASR open-source** e competitivo con le API
  proprietarie più forti; 0.6B miglior compromesso accuratezza/efficienza (TTFT fino a 92 ms,
  2.000 s di parlato trascritti in 1 s a concorrenza 128).
- Hosting ufficiale: Alibaba **QwenCloud/DashScope** `qwen3-asr-flash` (OpenAI-compatible, streaming),
  **quota gratuita 36.000 s (~10 ore), valida 90 giorni**, poi ~$0.000035/s (~$0.126/ora).
  Disponibile anche via OpenRouter.

Fonti: https://github.com/QwenLM/Qwen3-ASR · https://arxiv.org/html/2601.21337 · https://www.alibabacloud.com/help/en/model-studio/qwen-asr-api-reference

### 3. Altri considerati (scartati o marginali)
- **NVIDIA Nemotron ASR 3.5 / Riva / K2**: K2 è in famiglia NVIDIA ma l'implementazione locale
  affidabile oggi è `parakeet.cpp`/`transcribe.cpp` su Parakeet; Nemotron-ASR è orientato allo streaming server-side.
- **Moonshine (Useful Sensors)**: modello tiny velocissimo ma pensato per comandi brevi in inglese, non per dettatura italiana.
- **Deepgram Nova-3 / AssemblyAI / Gladia**: buoni su audio reale ma **crediti una tantum o a pagamento**,
  non free tier permissivo stile Groq.
- **Whisper v4 OpenAI**: non rilasciato al momento della ricerca; `gpt-4o-transcribe` è API a pagamento
  (nessun free tier reale).

## Free tier a confronto (fonte: pagine pricing ufficiali, 2026)

| Provider | Free tier | Durata | Note |
|---|---|---|---|
| **Groq** (attuale) | Rate-limited, molto permissivo | illimitata | 28.800 s/giorno, 7.200 s/ora |
| AssemblyAI | $50/mese di credito (~13.500 min) | ricorrente | non richiede carta |
| NVIDIA NIM (build.nvidia.com) | 1.000–5.000 crediti, 40 req/min | una tantum (richiedibile) | Parakeet hosted, ma non per uso quotidiano |
| Alibaba Qwen3-ASR-Flash | 10 ore | 90 giorni | poi $0.126/ora |
| Deepgram | $200 credito | una tantum | ~26k–55k minuti |
| Google Cloud STT | 60 min/mese | illimitata | richiede carta |
| OpenAI Whisper/gpt-4o-transcribe | nessuno | – | solo prova $5 |

Fonti: https://deepgram.com/pricing · https://www.assemblyai.com/pricing · https://prodsens.live/2026/03/08/is-nvidia-nims-free-tier-good-enough-for-a-real-time-voice-agent-demo/

## Raccomandazione

Per dettatura **italiana**, gratuita e **veloce**, con free tier permissivo:

1. **Tenere whisper-large-v3-turbo su Groq** è ancora la scelta migliore end-to-end:
   unico provider con free tier davvero permissivo e latenza ~190 ms.
2. **Gap di precisione "gratuito" a portata di mano**: su Groq stesso è disponibile
   `whisper-large-v3` (WER ~10,3% vs ~12%). È lo stesso provider, stessa API, cambio di una
   costante: guadagno di accuratezza con costo trascurabile in latenza (189× vs 216×).
3. **Parakeet TDT v3 locale** è l'opzione più promettente *per il futuro offline*: velocissimo
   su CPU, supporta l'italiano, licenza permissiva — ma richiede di sostituire il runtime
   `pywhispercpp` con `transcribe.cpp`/`parakeet.cpp`, ed è più debole su audio difficile/vocaboli tecnici.
4. **Qwen3-ASR-1.7B** è il modello *più nuovo e potenzialmente più preciso* (SOTA open-source,
   streaming, italiano), ma hosted è a pagamento dopo 10 ore gratuite e la latenza su DashScope
   non è paragonabile a quella Groq; localmente serve torch/vLLM (pesante rispetto al runtime attuale).

### Prossimo passo consigliato (nessun codice ancora)
Misurare su un campione di audio italiano reale la differenza di WER tra `whisper-large-v3`
e `whisper-large-v3-turbo` (stesso endpoint Groq) prima di decidere il cambio — è il cambio
a rischio zero. Parakeet/Qwen3 vanno valutati solo in modalità locale con un benchmark dedicato.
