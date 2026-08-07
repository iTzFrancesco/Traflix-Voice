# Traflix Voice — report completo di latenza e regressioni

Data del report: 2026-08-08  
Percorso analizzato: hotkey → Rust/Tauri → sidecar Python → cattura audio → WAV/multipart → Groq → evento risultato → paste/UI.

## Stato finale dopo i 10 round aggiuntivi (R39–R48)

La baseline è stata acquisita prima di R39 e le misure finali dopo R48, con lo
stesso ambiente e gli stessi script. I valori locali escludono rete e inferenza
per rendere confrontabile il codice dell'applicazione.

| Misura | Prima di R39 | Dopo R48 | Variazione |
|---|---:|---:|---:|
| Stop → richiesta, mediana | 0,469 ms | 0,328 ms | −30,1% |
| Stop → richiesta, p95 | 0,592 ms | 0,417 ms | −29,6% |
| Stop → risultato, mediana | 0,470 ms | 0,329 ms | −30,0% |
| Stop → risultato, p95 | 0,593 ms | 0,418 ms | −29,5% |
| Cloud path deterministico, mediana | 0,457 ms | 0,220 ms | −51,9% |
| Cloud path deterministico, p95 | 0,760 ms | 0,322 ms | −57,6% |
| Groq reale, mediana | 194,3 ms | 188,6 ms | −2,9%* |
| Groq reale, media | 180,0 ms | 178,3 ms | −0,9%* |

\* La rete e il servizio remoto dominano la misura live. Tutte le 11 chiamate
finali (1 warm-up + 10 misurate) hanno restituito `result`. Il p95 live è salito
da 196,9 a 312,0 ms per un singolo spike (massimo 276,9 ms, quantile interpolato
su soli 10 campioni), mentre minimo e massimo finali sono stati 119,2 e 276,9 ms.
Il dato viene riportato per completezza e non attribuito al codice locale.

La prima misura storica del progetto era 50,340 ms stop→request: il valore
finale di 0,328 ms rappresenta una riduzione complessiva di circa −99,35%, ossia
un percorso locale circa 153 volte più rapido. La precedente baseline finale
stabile era 0,264 ms sul solo cloud path; il nuovo 0,220 ms aggiunge un ulteriore
−16,7%. La baseline di 0,457 ms congelata a inizio ciclo include la normale
varianza della macchina condivisa, ma è riportata senza selezionare i campioni.

## Risultato del ciclo precedente da 20 round

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

## I 10 round aggiuntivi profondi

| Round | Commit | Modifica | Misura osservata |
|---:|---|---|---|
| 39 | `137d446` | Il trimming restituisce esplicitamente “nessun parlato” ed elimina il secondo scan | Caso pienamente attivo 166,9 → 146,1 µs (−12,4%) |
| 40 | `07579a6` | Scan adattivo: una maschera per clip brevi, blocchi limitati per dettati lunghi | 30 s con margini 762 → 394 µs; 3 min 6,08 → 1,28 ms |
| 41 | `87e6659` | Prefissi multipart precompilati per tutte le lingue della UI | Builder italiano 2,26 → 2,06 µs |
| 42 | `44d819e` | PCM normalizzato scritto direttamente in `int16`, con fallback di clipping | Clip da 30 s circa 389 → 56 µs nel test isolato |
| 43 | `342f801` | CookieJar escluso dal client bearer stateless | Tratto HTTP isolato 101,7 → 54,4 µs |
| 44 | `f29d540` | `httpx.Request` + `Client.send` evita merge ripetuti | Cloud path 0,221 → 0,211 ms nel confronto del round |
| 45 | `be75b4d` | Rimossi header `Connection` e compressione ridondanti | Tratto HTTP 50,9 → 49,4 µs |
| 46 | `cab7faf` | Worker di trascrizione unico, seriale e pre-riscaldato | Dispatch 134,3 → 35,9 µs (−73,3%) |
| 47 | `89a0258` | Blocchi mono 1D, coda bloccante con sentinel e niente copie dopo stop | `SimpleQueue.get`: 299 → 207 ns; stop su 64 blocchi 0,464 → 0,462 ms |
| 48 | `e054c81` | IPC stop prima dello stato React e rimozione log dal percorso critico | Bundle principale 55.464 → 54.332 byte; nessun lavoro UI prima dell'invoke |

## Esperimenti profondi scartati in questo ciclo

- Fast path del client senza lock: soltanto 343 → 332 ns, non sufficiente a
  giustificare una semantica concorrente più complessa.
- Payload WAV/multipart completamente fuso: migliorava i clip lunghi, ma
  peggiorava il caso breve comune da 7,33 a 10,20 µs; non integrato.
- Chiamata diretta al transport HTTPX: il mock scendeva a circa 33 µs, ma
  avrebbe bypassato comportamento pubblico del client, proxy, auth e redirect;
  il risparmio locale non giustifica il rischio di compatibilità.
- HTTP/2 e preconnessioni artificiali restano esclusi: nelle prove precedenti
  non avevano ridotto in modo ripetibile la latenza live.

## Regressione finale dopo R48

- 54 test Python passati;
- payload WAV e multipart verificati, inclusi fast path PCM, clipping, lingua e
  auto-detect;
- silenzio breve/lungo, campioni non finiti e trimming con padding verificati;
- worker caldo riutilizzato sullo stesso thread e shutdown verificato;
- callback mono, sentinel immediato e nessuna coda tardiva dopo stop verificati;
- benchmark deterministico finale: 5.000 iterazioni stop e 10.000 cloud path;
- benchmark Groq reale: 11/11 risposte `result`, nessuna chiave stampata;
- build TypeScript/Vite passata;
- `cargo fmt --check` passato;
- 9 test Rust passati;
- `cargo clippy -- -D warnings` passato;
- smoke test sidecar `init → get_status → quit` passato con stub PortAudio;
- working tree e file ignorati controllati prima della pubblicazione.

La chiave Groq non è presente nel codice, nel report o nei commit. `.env` resta
ignorato da Git. Anche dopo questi round non conviene riscrivere il backend cloud
in C/C++/Rust: il tratto locale è 0,220–0,329 ms, mentre la mediana live è
188,6 ms; il limite residuo è quasi interamente rete/provider.
