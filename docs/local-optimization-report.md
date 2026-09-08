# Traflix Voice — ottimizzazione velocità trascrizione LOCALE

Data: 2026-09-08. Perimetro: solo `transcribe_local` e caricamento modelli locali.
**Il percorso cloud/Groq non è stato toccato** (stesso endpoint, stesso modello,
stessi test invariati e verdi).

## Metodo (sandbox)

- Harness: `scripts/benchmark_local.py` (warmup + rep, mediana, RTF, WER, `--json-out`),
  stesse convenzioni di `scripts/benchmark_cloud_path.py`.
- Fixture: 4 spezzoni FLEURS `it_it` (5.3 / 7.1 / 8.6 / 13.6 s) + 1 clip da 7.3 s con
  2 s di silenzio ai bordi (caso hotkey reale), tutti con transcript noto.
- Guardia qualità: ogni round che cambia il decode deve mantenere WER invariato.
- Macchina di misura: CPU condivisa debole → contano i rapporti relativi, non gli assoluti.

## Baseline (R1, R8)

| Backend | 5.3 s | 7.1 s | 8.6 s | 13.6 s | WER |
|---|---|---|---|---|---|
| Parakeet int8 (R1) | 1.78 s | 1.68 s | 1.89 s | 2.69 s | 0.0 |
| Turbo Q5 whisper.cpp (R8) | 53.6 s | 53.1 s | 55.9 s | 55.8 s | 0.0–0.033 |

Turbo è piatto al variare della lunghezza: l'encoder large gira sempre sulla
finestra da 30 s. Parakeet scala linearmente ed è ~30× più veloce a pari testo.

## Round

| Round | Modifica | Risultato | Verdetto |
|---|---|---|---|
| R1 | Baseline Parakeet (4 thread) | 1.7–2.7 s, WER 0.0 | base |
| R2/R3/R4 | Thread Parakeet 1/2/8 | 1 thread peggio su clip lunghi; 2/4/8 entro rumore | tenere 4 |
| R5 | Profilo accept vs decode | decode >97% del tempo | ottimizzare = ridurre i frame |
| R6 | Trim su clip FLEURS | −16–20% dove c'è silenzio, neutro altrove | ok |
| R7 | Clip con 2 s di silenzio ±trim | 1.48 → 1.25 s (−16%), WER 0.0 | **applicato** |
| R8 | Baseline Turbo Q5 | ~54 s piatti, WER ~0 | base |
| R9/R10 | Thread Turbo 2/8 | 98 s / 43.6 s vs 53.6 s default (4) | 8 vince |
| R11 | Replica default vs 8 | 55.7 vs 38.6 s (−31%) | **applicato: min(8, cpu)** |
| R12 | Lingua `auto` vs `it` | 78.5 vs 38.6 s | tenere `it` forzato (già così) |
| R13 | `beam_size=1` | non esposto da pywhispercpp (default già greedy) | n/a |
| R14 | `greedy.best_of=1` | 36.5 vs 38.6 s, segnale debole | scartato |
| R15 | `single_segment=true` | 38.6 s identici | scartato |
| R16 | Trim su Turbo | neutro (encoder sempre full-window) | innocuo, condiviso |
| R17/R18 | faster-whisper int8 (4/8 thread) | 28.1/29.3 s, stesso testo | scartato: −27% ma +~1 GB dipendenze, 19× più lento di Parakeet |
| R19 | Overhead adapter Parakeet | entro rumore (µs–ms) | trascurabile |
| R20 | 1 s silenzio → 0.37 s inferenza sprecata | output vuoto | **gate: skip + result vuoto** |
| R21 | VAD whisper (`vad=true`) | modello non nel repo ufficiale, nuova fonte + rischio qualità per risparmi solo decoder-side | non eseguito |
| R22 | Thread Parakeet 6 | 1.39 s, entro rumore | tenere 4 |
| R23 | Stesso clip 2× | output identico | deterministico |
| R24 | Download modello VAD | filename errato + vedi R21 | abbandonato |
| R25/R26 | `temperature=0.0` esplicita | è già il default documentato | non eseguito |
| R27/R28/R29 | Micro: cache load, concat+cast, verify | 0.4 / 14.7 / 25–62 µs | trascurabili |
| R30 | Path produzione Parakeet end-to-end | 1.32 s, result corretto | **validato** |
| R31 | Overhead ThreadPool `transcribe_local` | ~1 ms vs secondi di inferenza | scartato (0.07%) |
| R33 | Path produzione Turbo (trim+t8) | 42.3 s, testo corretto | **validato** |
| R34 | Costo trim isolato | 159 µs | trascurabile |
| R35 | 3 s silenzio via gate | 0.2 ms vs ~1 s | **validato** |
| R37 | Parakeet `auto` vs `it` | testi identici | ok |
| R38 | Input float64 non-contiguo | testo corretto | robusto |
| R43 | RSS dopo load | Turbo 672 MB, Parakeet 723 MB | entrambi < 1 GB |
| R48 | Clip lunga 26.3 s Parakeet | 5.59 s (RTF 4.7×), testo corretto | scala linearmente |

## Modifiche applicate (solo locale)

1. `whisper_engine/model.py`: `Model(..., n_threads=min(8, cpu))` (~−30% Turbo).
2. `whisper_engine/transcriber.py`: trim del silenzio + gate anti-silenzio in
   `transcribe_local` (condiviso dai due backend; neutro per Turbo, −16% Parakeet
   su audio reale con pause); normalizzazione input contiguo float32 zero-copy.
3. `whisper_engine/parakeet.py`: `model_type="nemo_transducer"` (richiesto dalle
   sherpa-onnx moderne) + override `num_threads` per i round.

## Effetto finale misurato

| Caso | Prima | Dopo |
|---|---|---|
| Parakeet, dettato con pause (7.3 s) | 1.48 s | **1.25–1.32 s** |
| Turbo Q5, clip 5.3 s | 53–56 s | **~42 s** |
| Silenzio accidentale (3 s) | ~1 s inferenza | **0.2 ms** (gate) |
| WER fixture italiane | 0.0 | 0.0 (invariato) |
| RAM a modello caricato | — | 672 MB Turbo / 723 MB Parakeet |

Test: 113 verdi (`test_whisper_engine` + cloud/audio), `tsc` pulito.
Raw JSON dei round: `/tmp/rounds/R*.json` (fuori repo, come da policy sui dati).
