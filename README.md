# Traflix Voice

**Dettatura vocale locale con Whisper** -- trascrivi la tua voce in testo senza mai uscire dal tuo computer.

Traflix Voice e un'applicazione desktop che sfrutta [faster-whisper](https://github.com/SYSTRAN/faster-whisper) per trascrivere l'audio del microfono in tempo reale. Tutto gira in locale: nessun dato viene inviato a server esterni, nessun abbonamento richiesto. Tieni premuta la hotkey, parla, rilascia: il testo appare dove stavi scrivendo.

---

## Feature principali

- **Trascrizione 100% offline** -- privacy totale, nessuna connessione internet necessaria dopo il download del modello.
- **Hotkey globali (hold-to-speak)** -- tieni premuto `Ctrl+Alt` (o la combinazione che preferisci) per registrare; rilascia per trascrivere.
- **Auto-paste** -- il testo trascritto viene incollato automaticamente nell'applicazione attiva.
- **Multi-modello** -- scegli tra 4 modelli Whisper (Tiny, Base, Small, Medium) in base alle tue esigenze di velocita e precisione.
- **Pre-caricamento modello** -- il modello predefinito viene caricato in memoria all'avvio per trascrizioni istantanee.
- **Download on-demand** -- i modelli vengono scaricati solo quando servono, direttamente dall'app.
- **Overlay compatto** -- widget minimale always-on-top con logo, nome e visualizzatore audio; trascinabile e doppio-click per riaprire il pannello.
- **Cronologia trascrizioni** -- le ultime 50 trascrizioni vengono salvate con timestamp; click per copiare.
- **Statistiche di utilizzo** -- parole totali, WPM medio e tempo di dettatura, coerenti con la cronologia.
- **Visualizzatore audio** -- forma d'onda in tempo reale durante la registrazione.
- **System tray** -- l'app si minimizza nella tray; rimane sempre pronta all'uso.
- **Selezione dispositivo audio** -- scegli il microfono da usare tra quelli disponibili nel sistema.
- **Multi-lingua** -- italiano, inglese, francese, tedesco, spagnolo, portoghese e auto-detect.
- **Supporto GPU** -- accelerazione CUDA opzionale per trascrizioni piu veloci.

---

## Requisiti di sistema

| Componente        | Requisito minimo                            |
| ----------------- | ------------------------------------------- |
| Sistema operativo | Windows 10/11 (macOS e Linux sperimentali)  |
| Python            | 3.8+                                        |
| Rust toolchain    | stable (con `cargo`)                        |
| RAM               | 4 GB+ (8 GB consigliati per modello Medium) |
| Spazio disco      | ~2.5 GB per tutti i modelli                 |

---

## Installazione

### 1. Clona il repository

```bash
git clone https://github.com/iTzFrancesco/Traflix-Voice.git
cd Traflix-Voice
```

### 2. Installa le dipendenze Python

```bash
pip install -r src-tauri/requirements.txt
```

Le dipendenze Python sono:

- `faster-whisper` -- motore di trascrizione
- `sounddevice` -- cattura audio dal microfono
- `numpy` -- elaborazione array audio
- `huggingface_hub` -- download modelli

### 3. Avvia in modalita sviluppo

```bash
cargo tauri dev
```

Al primo avvio, vai nella sezione **IA** dell'app e scarica almeno un modello (consigliato: **Small**).

---

## Modelli Whisper

L'app supporta quattro modelli della famiglia faster-whisper. Ogni modello puo essere scaricato direttamente dall'interfaccia.

| Modello    | Dimensione | RAM   | Velocita | Precisione | Note                                                     |
| ---------- | ---------- | ----- | -------- | ---------- | -------------------------------------------------------- |
| **Tiny**   | 75 MB      | ~1 GB | *****    | *          | Velocissimo. Ideale per test rapidi.                     |
| **Base**   | 145 MB     | ~1 GB | ****     | **         | Leggero e reattivo. Buon punto di partenza.              |
| **Small**  | 466 MB     | ~2 GB | ***      | ***        | **Consigliato.** Miglior equilibrio velocita/precisione. |
| **Medium** | 1.5 GB     | ~5 GB | **       | ****       | Alta precisione su accenti regionali e termini tecnici.  |

I modelli vengono salvati nella cartella dati dell'applicazione (`AppData` su Windows) sotto `models/`.

---

## Utilizzo

### Flusso base

1. **Avvia l'app** -- il motore Whisper si inizializza e pre-carica il modello Small.
2. **Scarica un modello** -- dalla tab IA, clicca "Scarica" sul modello desiderato.
3. **Seleziona il modello** -- clicca "Seleziona" per attivarlo (il modello attivo mostra un badge verde).
4. **Parla** -- tieni premuta la hotkey (default: `Ctrl+Alt`), parla nel microfono, rilascia.
5. **Il testo appare** -- con auto-paste attivo, il testo viene incollato direttamente dove stai scrivendo.

### Overlay

Quando chiudi la finestra principale, l'app mostra un widget compatto always-on-top:

- **Idle** -- logo + scritta "Traflix Voice"
- **Recording** -- le barre audio animate sostituiscono la scritta
- **Processing** -- uno spinner sostituisce la scritta
- **Doppio click** -- riapre la finestra principale
- **Trascinamento** -- il widget e trascinabile ovunque sullo schermo

### Hotkey

| Azione          | Scorciatoia predefinita |
| --------------- | ----------------------- |
| Registra (hold) | `Ctrl+Alt`              |

La hotkey e personalizzabile dalla sezione Tasti. Sono supportate combinazioni con `Ctrl`, `Alt`, `Shift` e tasti funzione.

### Impostazioni

- **Sorgente audio** -- scegli il microfono di input.
- **Lingua trascrizione** -- italiano, inglese, francese, tedesco, spagnolo, portoghese, auto-detect.
- **Dispositivo di calcolo** -- CPU, GPU (CUDA), o auto-detect.
- **Incolla automatica** -- attiva/disattiva l'incollaggio automatico del testo trascritto.

---

## Architettura

```
+------------------+      stdin/stdout (JSON)      +--------------------+
|   Tauri (Rust)   | <---------------------------> |  Python sidecar    |
|                  |                               |  (whisper_engine)  |
|  - Global hotkey |                               |  - faster-whisper  |
|  - Clipboard     |                               |  - sounddevice     |
|  - System tray   |                               |  - Audio capture   |
|  - Settings I/O  |                               |  - Transcription   |
+--------+---------+                               +--------------------+
         |
         | Tauri events + invoke
         |
+--------+---------+
|  Frontend (JS)   |
|  Vanilla JS/HTML |
|                  |
|  - UI / tabs     |
|  - Model catalog |
|  - Waveform viz  |
|  - Stats display |
+------------------+
```

- **Tauri 2 (Rust)** -- shell dell'app, gestione hotkey globali (`tauri-plugin-global-shortcut` + `rdev`), clipboard (`tauri-plugin-clipboard-manager`), spawn del processo Python (`tauri-plugin-shell`), persistenza impostazioni/statistiche su disco, icona nella system tray.
- **Vanilla JS + HTML/CSS** -- interfaccia utente senza framework, comunicazione con Rust tramite `invoke()` e listener di eventi Tauri.
- **Python sidecar (`whisper_engine.py`)** -- processo figlio che riceve comandi via stdin (JSON) e restituisce risultati via stdout. Gestisce download dei modelli da Hugging Face, cattura audio con `sounddevice`, trascrizione con `faster-whisper`.

---

## Build per produzione

```bash
cargo tauri build
```

L'installer generato si trova in `src-tauri/target/release/bundle/`. Su Windows viene prodotto un file `.msi` e/o `.exe`.

---

## Struttura del progetto

```
traflix-voice/
  src/
    index.html          # Interfaccia utente principale
    overlay.html        # Widget overlay compatto
    main.js             # Logica frontend
    styles.css          # Stili dell'applicazione
    export-functions.js # Funzionalita di esportazione
    assets/             # Logo e suoni notifica
  src-tauri/
    src/
      lib.rs            # Core Rust: comandi Tauri, hotkey, tray, IPC
      main.rs           # Entry point
    whisper_engine.py   # Sidecar Python: trascrizione Whisper
    requirements.txt    # Dipendenze Python
    tauri.conf.json     # Configurazione Tauri
    Cargo.toml          # Dipendenze Rust
```

---



**Traflix Voice -- Dettatura vocale locale fornita da  OpenAI Whisper.**
**© 2026 - Traflix - All rights reserved**