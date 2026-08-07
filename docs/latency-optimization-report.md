# Traflix Voice — report completo di latenza e regressioni

Data del report: 2026-08-08  
Percorso analizzato: hotkey → Rust/Tauri → sidecar Python → cattura audio → WAV/multipart → Groq → evento risultato → paste/UI.

## Risultato finale

La baseline isolata all’inizio di questo ciclo era:

| Misura | Prima dei 20 round | Dopo i 20 round | Variazione |
|---|---:|---:|---:|
| Stop → richiesta, mediana | 0,504 ms | 0,369 ms | −26,8% |
| Stop → richiesta, p95 | 0,613 ms | 0,446 ms | −27,2% |
| Stop → risultato, mediana | 0,506 ms | 0,371 ms | −26,7% |
| Cloud path deterministico, mediana | 0,468 ms | 0,264 ms | −43,6% |
| Groq reale, mediana | 189,0 ms | 126,4 ms | −33,1%* |

\* La misura Groq reale dipende da rete, routing, carico e inferenza del servizio remoto; la riduzione è indicativa, non una garanzia fissa. Le 6 richieste finali hanno restituito `result`.

Scenario con 4,5 secondi di audio, di cui solo 0,5 secondi parlato:

- prima del trimming: 1.281,5 ms di mediana;
- dopo il trimming: 193,4 ms di mediana;
- payload: 72.000 → 13.119 campioni;
- riduzione osservata: circa −84,9%.

## Fasi precedenti già completate

Il primo benchmark storico del progetto usava un polling stop da circa 50 ms:
`stop_to_request 50,340 ms`, `stop_to_result 50,342 ms`. Il lavoro precedente ha portato il percorso locale sotto 1 ms e ha preparato la base cloud.

| Commit/fase | Modifica | Misura o risultato |
|---|---|---|
| `5278d83` | Calibrazione percettiva del volume meter | Widget più sensibile ai segnali bassi |
| `7ec52e8` | Amplificazione visuale del parlato quieto | Widget più leggibile senza cambiare audio inviato |
| `20b2c86` | Client cloud riutilizzabile e volume isolato nell’overlay | Eliminata ricostruzione inutile del client |
| `d0ffad8` | Riduzione del blocco di cattura | Cattura più reattiva |
| `e98361d` | Paste del risultato prima degli aggiornamenti React | Il testo arriva prima alla finestra attiva |
| `444a114` | Lockfile npm sincronizzato | Installazione riproducibile |
| `f64b0f9` | Fix compilazione Rust non-Windows | CI/test multipiattaforma |
| `322d54d` | Niente probe locali in modalità cloud | Startup cloud più leggero |
| `0895b8a` | Listener React con dipendenze più strette | Meno reregistrazioni |
| `baf70fa` | Primo benchmark end-to-end cloud | Misurazione ripetibile introdotta |
| `1b01356` | Stop che sveglia subito la coda Python | Mediana R1 circa 0,167 ms |
| `f6428c6` | WAV cloud preparato direttamente | Mediana R2 circa 0,129–0,132 ms |
| `757847c` | Eliminazione copie audio ridondanti | Preparazione audio circa 1,0327 → 0,1297 ms |
| `5b39388` | Prewarm del client cloud | Cold start circa 170,376 → 0,447 ms locale |
| `332e883` | Comando Rust stop IPC dedicato | Stop IPC circa 0,122–0,124 ms |
| `06bd131` | Paste avviato prima degli update React | Risultato non bloccato dal render |
| `f73eb2a` | Persistenza spostata fuori dal percorso critico | UI/paste non attendono history/stats |
| `e0dd509` | Bypass del wrapper SDK Groq | Client path circa 0,6458 → 0,2285 ms |

## Ciclo immediatamente precedente

| Commit | Modifica | Risultato |
|---|---|---|
| `d795709` | Benchmark Groq live senza salvare la chiave | Misurazione reale ripetibile |
| `dd23cb2` | `SimpleQueue` per i blocchi audio | Coda circa 2,565 → 0,211 µs |
| `6f8ddd4` | Riutilizzo del buffer nel volume meter | circa 47,95 → 44,62 µs |
| `6bb9820` | Blocchi audio da 2048 a 1024 campioni | Finestra 128 → 64 ms |
| `d2a727f` | Authorization header nel client keep-alive | Path circa 0,376 → 0,365 ms |
| `35587cb` | Conversione WAV con meno allocazioni | circa 0,0160 → 0,0158 ms |
| `00c5f12` | Scrittura IPC diretta | Stop circa 0,515 → 0,503 ms |
| `840f9a3` | Flatten mono senza copia aggiuntiva | circa 0,559 → 0,526 ms su 8 blocchi |
| `0e927bc` | Trimming del silenzio ai bordi cloud | Scenario margini 1.281,5 → 192,1 ms |
| `45c9a69` | Stop IPC Rust sincrono | Future rimosso dal comando critico |

La baseline finale di questo ciclo precedente, misurata isolatamente e riutilizzata all’inizio del presente ciclo, era circa `0,504 ms` stop→request.

## I 20 round di questo ciclo

| Round | Commit | Modifica | Prima → dopo |
|---:|---|---|---|
| 1 | `b479c73` | Multipart Groq costruito direttamente invece dell’encoder HTTPX | 0,2285 → 0,1564 ms nel componente |
| 2 | `1b3a2bb` | Scan dei bordi audio con maschera/argmax e fast path | Audio pienamente attivo 0,2536 → 0,0006 ms |
| 3 | `ebdc313` | Short-circuit efficiente per audio completamente silenzioso | Silenzio lungo circa 0,0667 → 0,0569 ms |
| 4 | `bf68a17` | Nessuna chiamata Groq se la registrazione è muta | Richiesta HTTP → 0 richieste |
| 5 | `e7d0922` | Frammenti statici multipart memorizzati | 0,0030 → 0,0017 ms nel builder |
| 6 | `dc6c5b6` | `struct.Struct` riutilizzato per l’header WAV | Micro-riduzione, circa 0,01597 → 0,01583 ms |
| 7 | `aac0be5` | Polling hotkey Rust da 16 a 8 ms | Finestra massima hotkey dimezzata |
| 8 | `2da4c9a` | IPC generico Rust reso sincrono | Eliminato future non necessario nello start/config |
| 9 | `a9da7e2` | Overlay sospende l’animation loop quando idle | Meno CPU concorrente durante l’inferenza |
| 10 | `fda9955` | Listener Python frontend mantenuto stabile | Niente unsubscribe/subscribe al cambio provider |
| 11 | `11152cf` | Attesa clipboard prima di Ctrl+V da 50 a 20 ms | −30 ms sul tratto paste |
| 12 | `5e81a03` | URL Groq convertito una sola volta in `httpx.URL` | 0,1494 → 0,1077 ms nel componente |
| 13 | `da6ffcc` | Fast path per risposta HTTP 200 | 0,1836 → 0,1787 ms nel componente |
| 14 | `5b16927` | Decode UTF-8 del body già bufferizzato | Cloud path 0,320 → 0,261 ms |
| 15 | `b746558` | Persistenza `groq_usage.json` serializzata in background | Ritorno 0,8582 → 0,3609 ms; file verificato scritto |
| 16 | `4d0922b` | Throttle volume prima della scansione NumPy | Burst di callback: una sola elaborazione necessaria |
| 17 | `c52e300` | Fixture benchmark reso non silenzioso | Benchmark corretto dopo l’introduzione dello skip mute |
| 18 | `69b2fb5` | Blocchi audio da 1024 a 512 campioni | Finestra cattura 64 → 32 ms, stop invariato (~0,44 ms) |
| 19 | `1a4b104` | `InputStream` fissato a `float32` | Evitata conversione implicita del backend audio |
| 20 | `68a4c07` | Stop frontend fire-and-forget | Invio IPC avviato senza attendere una Promise inutile |

## Esperimenti scartati

Sono stati provati anche HTTP/2, `trust_env=False`, JSON compatto/UTF-8 e varianti BytesIO/bytes. Sono stati lasciati fuori perché non hanno migliorato la misura in modo ripetibile, oppure hanno peggiorato serializzazione o compatibilità.

## Controllo funzionale finale

Verifiche eseguite sullo stato finale:

- 46 test Python passati;
- payload WAV mono PCM 16-bit verificato;
- payload multipart verificato con modello, lingua, formato e file;
- test esplicito: audio muto non genera richieste HTTP;
- test esplicito: audio quieto viene mantenuto dal trimming;
- test del flusso engine con blocchi multipli e risultato;
- smoke test del protocollo sidecar `init → get_status → quit` passato con stub PortAudio;
- build TypeScript/Vite passata;
- `cargo fmt --check` passato;
- 9 test Rust passati;
- `cargo clippy -- -D warnings` passato;
- working tree controllato senza modifiche parziali.

Il primo smoke test reale del sidecar Linux non poteva caricare PortAudio perché la libreria non è installata nell’ambiente di test; lo stesso protocollo è poi passato con il solo stub audio usato dalla suite. Non è una regressione del codice.

## Sicurezza e Git

La chiave Groq è stata usata soltanto nei processi di benchmark e non compare in questo report, nel codice o nei commit. Il file locale `.env` resta ignorato da Git e non viene pubblicato.

Il backend resta Python + Rust: il percorso locale misurato è già sotto il millisecondo, quindi una riscrittura completa in C/C++/Rust non porterebbe vantaggi proporzionati rispetto al tempo di rete e inferenza Groq.
