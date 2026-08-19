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

## Dieci round cloud-only aggiuntivi

Questo ciclo è stato riallineato alla richiesta di usare esclusivamente Groq
Cloud. L’esperimento sul riuso dell’executor locale è stato rimosso e non è
conteggiato. Sono state mantenute solo le modifiche condivise che incidono sul
percorso cloud: cattura audio, IPC, overlay, persistenza del risultato e
client HTTP.

| Round | Intervento | Prima → dopo | Evidenza |
|---:|---|---|---|
| 1 | Serializzazione compatta degli eventi `volume` | 56,761 → 9,591 ms / 20.000 eventi; 34 → 31 byte | `benchmark_ipc.py` |
| 2 | Scarto del volume prima di `JSON.parse` e `Set` statico degli stati | 108,780 → 9,263 ms / 200.000 eventi (−91,5%) | `benchmark_frontend_events.mjs` |
| 3 | Waveform con `transform: scaleY` e fattori precomputati | 5.739,054 → 5.320,687 ms / 100.000 frame (−7,3%) | `benchmark_overlay_animation.mjs` |
| 4 | Sessione audio isolata, sentinel idempotente e clock monotono | costo stop→request sub-ms; lieve overhead rispetto al vecchio sentinel, con stop cross-session eliminato | suite `TestRecordingSession` + latency loop |
| 5 | Una sola IPC per statistiche e lock separati per history/stats | 200.000 → 100.000 IPC; loop 1,220 → 0,786 ms | `benchmark_stats_flow.mjs` |
| 6 | Copia mono riusata nel volume e conversione WAV cloud senza min/max | audio 0,0303 → 0,0278 ms; WAV 0,0855 → 0,0586 ms | `benchmark_cloud_audio.py` |
| 7 | WAV+multipart costruiti direttamente senza `BytesIO` intermedio | 0,0847 → 0,0597 ms (−29,5%); payload identico, 128.573 byte | `benchmark_cloud_payload.py` |
| 8 | Reset orario usage e rotazione client fuori dal lock | nessun lavoro aggiunto al percorso critico: usage resta su `groq-usage` executor | test tracker/client + cloud path |
| 9 | Chiusura esplicita delle response e classificazione robusta del 429 | 500 richieste concorrenti, 500 risultati, 0 errori; p95 0,961 ms con trasporto finto | `benchmark_cloud_stress.py` |
| 10 | Verifica aggregata finale e regressione cloud | cloud path mediana 0,125 ms, p95 0,219 ms; stop→request mediana 0,185 ms, p95 0,309 ms | latency/path loop, 47 test, build |

Le misure end-to-end sono locali e soggette allo scheduling di Windows; non
sono una misura della latenza reale Groq. Il round 4 privilegia la correttezza
dello stop tra registrazioni, quindi non viene presentato come guadagno di
microsecondi. Il percorso reale resta dominato da rete e provider.

### Verifiche di questo ciclo

- 47 test Python passati;
- `py_compile` di tutti i moduli Python passato;
- build TypeScript/Vite passata;
- `cargo fmt --check` passato;
- benchmark deterministici IPC, frontend, overlay, audio, payload, path,
  stop-latency e stress passati;
- working tree controllato su `main`, senza branch secondari;
- nessun commit o push eseguito.

Non è stato letto `.env` e non è stata effettuata una chiamata Groq reale: i
benchmark cloud usano trasporti HTTP finti per non esporre chiavi né confondere
il costo di rete con quello del codice locale. `cargo test`, `clippy` e build
Rust completi non sono stati rilanciati in questo ciclo per mantenere il focus
cloud richiesto e non ripetere il blocco di toolchain già rilevato.

## Nuovi 50 round — avanzamento chunk 1/5

Il primo chunk dei nuovi 50 round è completato. I round sono aggiuntivi rispetto
ai precedenti 10 e restano limitati al percorso cloud.

| Round | Miglioria | Evidenza |
|---:|---|---|
| 1 | RMS cloud con dot product, senza copia quadratica | Volume 0,0226 → 0,0179 ms mediana |
| 2 | Scala dB precomputata a livello di modulo | Nessuna variazione del livello calibrato nei test |
| 3 | Throttle volume basato sui campioni, senza `monotonic()` per blocco | Soglia stabile a 50 ms con blocchi variabili |
| 4 | Mask long-clip senza temporaneo `abs()` float | Output di trimming identico sui clip brevi/lunghi |
| 5 | Workspace booleano riusato durante la scansione lunga | Allocazione massima limitata a un blocco da 1 s |
| 6 | Normalizzazione dei caller cloud a mono float32 | Matrice mono accettata, multi-canale rifiutata prima dell’HTTP |
| 7 | Normalizzazione lingua (`AUTO`, spazi e maiuscole) | Campo multipart omesso per auto-detect |
| 8 | `getbuffer()` per il compatibile percorso WAV legacy | Payload 128.573 byte invariato |
| 9 | Lease del client HTTP durante la richiesta | Rotazione chiave non chiude client attivo |
| 10 | Decode UTF-8 tollerante per response provider malformate | Response corrotta produce comunque `result` controllato |

Risultati chunk 1: 56 test Python, build frontend, `py_compile`, `cargo
fmt --check`, security scan e `npm audit` passati; stress cloud 300/300 con 0
errori. Il candidato `np.any()` per il silenzio è stato scartato dopo il
benchmark perché peggiorava il caso comune; non è conteggiato come round.

## Nuovi 50 round — chunk 2/5: IPC e overlay cloud (round 11–20)

Il secondo chunk riduce il lavoro generato dagli aggiornamenti di volume durante
la registrazione cloud. Il dato ad alta frequenza viene consegnato direttamente
all'overlay, mentre gli stati applicativi restano sul canale della finestra
principale.

| Round | Miglioria | Evidenza |
|---:|---|---|
| 11 | Routing degli eventi `volume` solo alla finestra `overlay` | La finestra principale non viene più risvegliata per ogni campione del meter |
| 12 | Parser numerico compatto per payload `volume` | Nessun `JSON.parse` nel percorso normale del meter |
| 13 | Listener principale sincrono, senza callback `async` inutilizzata | Nessuna Promise allocata per la ricezione degli eventi non-volume |
| 14 | Fallback al broadcast se l'overlay non è disponibile | Nessun evento perso durante chiusura o ricreazione della finestra |
| 15 | Jitter delle barre generato una sola volta per sessione | Eliminato `Math.random()` dal loop per-frame |
| 16 | Look-up table per la curva di risposta del volume | 100.000 frame: 5.585,334 → 5.244,626 ms (−6,1%) |
| 17 | Supporto al formato `volume` legacy e clamp del valore | Payload negativi, oltre 100, incompleti o non numerici non propagano valori invalidi |
| 18 | Fast path degli stati compatti comuni dell'overlay | Gli stati `listening/processing/result/ready/error/rate_limit` evitano il parsing JSON completo |
| 19 | Rifiuto anticipato dei payload non stringa | Eventi IPC anomali terminano senza eccezioni o lavoro React |
| 20 | Riutilizzo della stringa UTF-8 presa in prestito nel sidecar | Evitata un'allocazione `.to_string()` per riga stdout; fallback preservato |

Misure del chunk 2: il benchmark di dispatch frontend passa da 61,726 a
8,615 ms su 200.000 eventi simulati (−86,0%); l'animazione passa da
5.585,334 a 5.244,626 ms su 100.000 frame (−6,1%). Lo stress cloud simulato
ha completato 300/300 richieste con 0 fallimenti e p95 di 1,321 ms. I valori
sono costi locali del codice e non includono la latenza di rete o inferenza
Groq.

### Verifiche chunk 2

- 56 test Python passati;
- `py_compile` dei moduli Python cloud passato;
- build TypeScript/Vite passata;
- `cargo fmt --check` passato;
- benchmark frontend, overlay, payload e stress passati;
- `npm audit --omit=dev --audit-level=high` passato con 0 vulnerabilità;
- nessun `.env` letto o modificato, nessun commit e nessun push eseguito.

## Nuovi 50 round — chunk 4/5: client HTTP e resilienza Groq (round 31–40)

Il quarto chunk lavora sul bordo HTTP cloud senza introdurre retry automatici:
un retry non controllato potrebbe duplicare una trascrizione e il relativo
consumo API. Le modifiche delimitano risorse, shutdown e prewarm del client.

| Round | Miglioria | Evidenza |
|---:|---|---|
| 31 | Pool HTTP limitato a una connessione keep-alive | Allineato al worker cloud seriale, meno contesa e risorse inutili |
| 32 | Timeout del pool esplicito a 5 s | Una concorrenza accidentale non può attendere indefinitamente una connessione |
| 33 | Close del client isolato dagli errori di cleanup | Chiusura/rotazione non maschera il risultato o lo shutdown principale |
| 34 | Check shutdown dopo trim/preparazione audio | Evitata una richiesta se la chiusura è iniziata prima dell'acquisizione client |
| 35 | Check shutdown appena prima dell'invio | Lease del client sempre rilasciato senza inviare lavoro tardivo |
| 36 | Shutdown dinamico osservabile durante la response | Risultato arrivato dopo la chiusura scartato, response comunque chiusa |
| 37 | `stream=False` esplicito su `Client.send` | Body Groq letto e chiuso in modo deterministico |
| 38 | Timeout HTTP classificato separatamente | UI riceve un errore azionabile senza confonderlo con rate limit |
| 39 | Prewarm con snapshot della chiave e guardia stale/shutdown | Un thread vecchio non può rimpiazzare il client della chiave nuova |
| 40 | Skip usage a durata nulla e redazione della chiave negli errori | Nessun task quota inutile; API key non viene inclusa nel messaggio mostrato |

Benchmark chunk 4: cloud path deterministico mediana 0,137 ms/p95 0,241 ms;
stop→request con client prewarmed mediana 0,174 ms/p95 0,236 ms; stress
concorrente 300/300 con 0 fallimenti e p95 1,401 ms. Le misure escludono rete
Groq reale e servono a controllare il costo del codice e la stabilità del
seam HTTP.

### Verifiche chunk 4

- 63 test Python passati, inclusi timeout, shutdown dinamico, stale prewarm e
  cleanup client;
- `py_compile` dei moduli cloud e benchmark passato;
- build TypeScript/Vite passata;
- `cargo fmt --check` e `cargo check --lib` passati;
- benchmark path, stop-latency e stress passati;
- nessun retry automatico introdotto, nessun `.env` letto o modificato;
- nessun commit e nessun push eseguito.

## Nuovi 50 round — chunk 3/5: persistenza del risultato cloud (round 21–30)

Questo chunk ottimizza il lavoro successivo alla risposta Groq: quota locale,
cronologia e statistiche. La durabilità resta sincrona/atomica dove già lo era;
viene eliminato solo il lavoro duplicato o evitabile.

| Round | Miglioria | Evidenza |
|---:|---|---|
| 21 | Rimosso il `reloadGroqUsage()` immediatamente successivo a `recordGroqUsage()` | Il record aggiorna già lo stato React: eliminati read/parse duplicati per risultato |
| 22 | Cache in memoria della quota nel renderer | Cache warm mediana 6,8283 → 0,8019 ms per write simulata (−88,3%) |
| 23 | Formattazione del reset orario solo al cambio bucket | Nessuna conversione locale ripetuta nello stesso intervallo orario |
| 24 | Validazione di durata finita e positiva + normalizzazione numerica | Durate NaN/negative e valori persistiti corrotti non alterano la quota |
| 25 | Inserimento ottimistico della nuova cronologia dopo salvataggio riuscito | La trascrizione cloud compare subito senza un secondo `get_history` |
| 26 | Guardie di generazione contro risposte asincrone obsolete | Cambio tab/clear/save non può sovrascrivere la cronologia con una risposta vecchia |
| 27 | Retention delle ultime 50 voci con `drain` | Evitata la nuova allocazione di `split_off` sul 51° risultato |
| 28 | JSON compatto per stats/history macchina-read | Stesso schema e parser invariato, meno byte e serializzazione per write |
| 29 | Cache del file `groq_usage.json` nel sidecar | Il tracker caldo non rilegge/reparsa il file ad ogni risultato; write resta atomica |
| 30 | Directory cache e no-op fast path del tracker | Nessuna directory/file operation per usage nullo; test cache e reset orario passati |

Il benchmark del tracker ha misurato 80 scritture: cache warm mediana 0,8019 ms
contro 6,8283 ms simulando un reload JSON ad ogni risultato (−88,3%). Il flusso
stats conferma 100.000 trascrizioni con 200.000 → 100.000 chiamate IPC (−50%).
La suite è salita a 58 test Python; il formato persistito e la scrittura
atomica non sono stati rimossi.

### Verifiche chunk 3

- 58 test Python passati, inclusi cache usage, reset orario e no-op tracker;
- `py_compile` dei moduli cloud e benchmark passato;
- build TypeScript/Vite passata;
- `cargo fmt --check` e `cargo check --lib` passati;
- benchmark persistence/stats passati;
- `npm audit --omit=dev --audit-level=high`: 0 vulnerabilità;
- nessun `.env` letto o modificato, nessun commit e nessun push eseguito.

## Nuovi 50 round — chunk 5/5: audit e rifinitura cloud (round 41–50)

L’ultimo chunk chiude il ciclo con ottimizzazioni trasversali sul risultato
Groq, sul meter e sui dashboard quota/history, più una regressione aggregata.
Non sono state aggiunte chiamate reali al provider né retry automatici.

| Round | Miglioria | Evidenza |
|---:|---|---|
| 41 | Separatori JSON compatti per gli eventi IPC di stato, oltre a `volume` | 20.000 eventi volume: applicazione 6,672 ms; payload 34 → 31 byte; `result` mantiene il serializer più rapido |
| 42 | Durata cloud normalizzata a numero finito non negativo | `NaN`, stringhe invalide e valori negativi diventano `0.0` prima del risultato |
| 43 | Limite di 512 caratteri sugli errori provider | Un errore anomalo non può gonfiare IPC/UI; chiave già redatta nel round 40 |
| 44 | Durata positiva verificata nel listener React | Nessun WPM infinito/negativo e nessun aggiornamento stats con durata corrotta |
| 45 | `Intl.DateTimeFormat` riusato per timestamp history | Formatter creato una volta, non per ogni risposta cloud |
| 46 | Deduplica degli stati di trascrizione nel renderer principale | Stati ripetuti non generano nuovi aggiornamenti React |
| 47 | Deduplica dei livelli volume consecutivi per sessione | Il meter non invia lo stesso valore IPC due volte di seguito |
| 48 | Risultato normalizzato con una sola `trim()` | Testo, conteggio parole e history condividono lo stesso buffer logico |
| 49 | Filtro history conserva l’indice originale durante la mappatura | Eliminato `indexOf` per ogni voce filtrata |
| 50 | Clamp dei contatori quota nei dashboard | Valori persistiti NaN/negativi non producono percentuali o CSS invalidi |

Regressione aggregata finale: frontend dispatch 56,698 → 8,285 ms su 200.000
eventi (−85,4%); overlay 5.738,757 → 5.275,886 ms su 100.000 frame
(−8,1%); payload cloud 0,0565 → 0,0448 ms con 128.573 byte identici;
tracker quota warm 0,7397 ms contro 7,0682 ms con reload ad ogni risultato
(−89,5%); stress 300/300, 0 fallimenti, p95 1,328 ms; cloud path mediana
0,140 ms/p95 0,232; stop→request mediana 0,179 ms/p95 0,303.

### Verifiche finali dei 50 round

- 66 test Python passati;
- `py_compile` di moduli Python e benchmark passato;
- build TypeScript/Vite passata;
- `cargo fmt --check` e `cargo check --lib` passati;
- benchmark IPC, frontend, overlay, payload, persistence, path, latency e
  stress passati;
- `npm audit --omit=dev --audit-level=high`: 0 vulnerabilità;
- nessun pattern di chiave/token nel codice, nessun `.env` letto o modificato;
- nessun commit, nessun branch secondario e nessun push su GitHub.

Il risultato complessivo è un percorso cloud più leggero prima della rete,
più stabile durante rotazioni/shutdown e con meno lavoro nel renderer. La
latenza reale Groq resta dipendente da rete, coda provider e inferenza: i
benchmark locali non vanno interpretati come latenza end-to-end del servizio.

## Altri 20 round — flusso cloud Registra → Stop → Groq

Questo ciclo è limitato al gesto di avvio/arresto della registrazione cloud e
alla preparazione immediatamente precedente all'HTTP Groq. Non sono state
modificate funzioni del provider locale, non sono stati aggiunti retry e non è
stata letta la configurazione `.env`.

| Round | Miglioria | Evidenza / controllo |
|---:|---|---|
| 1 | Polling hotkey cloud portato da 8 ms a 4 ms | Minore finestra tra pressione e evento, stesso meccanismo Windows |
| 2 | Guard readiness UI su `modelReadyRef` | La pressione usa lo stato più recente senza closure obsoleta |
| 3 | Riga IPC fissa per `listening` | Eliminata la serializzazione JSON dello stato di avvio |
| 4 | Riga IPC fissa per `processing` | Eliminata la serializzazione JSON dello stato di stop/elaborazione |
| 5 | `monotonic` importato una sola volta | Nessun import locale durante ogni trascrizione |
| 6 | Registrazione a un solo blocco senza `concatenate` | Evitata una copia per clip cloud molto brevi |
| 7 | Fast path array mono `float32` 1-D | Il buffer già acquisito viene riusato |
| 8 | Fast path matrice mono `float32` | Vista sulla colonna senza nuova allocazione |
| 9 | Test di regressione IPC dei due stati caldi | Riga prodotta byte-per-byte e con newline corretto |
| 10 | Test di riuso del buffer cloud | Identità dell'array preservata prima dell'encode |
| 11 | Normalizzazione lingua canonica senza `str/strip/lower` | `it/en/fr/de/es/pt` passano senza allocazione intermedia |
| 12 | Normalizzazione durata con fast path `float` finito | Il valore già valido viene restituito invariato |
| 13 | Snapshot del provider all'inizio della sessione | Il percorso scelto resta stabile durante drain e encode |
| 14 | Provider memorizzato nella `_RecordingSession` | Un toggle arrivato prima dell'esecuzione del worker non devia il clip |
| 15 | Regressione provider-toggle durante cattura | Cloud chiamato, local non chiamato anche dopo il cambio impostazione |
| 16 | Debounce nativo hotkey ridotto a 32 ms | Il latch `active` continua a impedire ripetizioni mentre il tasto è premuto |
| 17 | Cooldown UI start ridotto a 80 ms | Il doppio evento accidentale resta filtrato con meno attesa |
| 18 | Stop azzera il cooldown start | Una nuova registrazione può seguire subito lo stop |
| 19 | Benchmark stop→request su 1/8/64 blocchi | Mediana dopo: 0,176 / 0,176 / 0,232 ms; p95: 0,226 / 0,223 / 0,331 ms |
| 20 | Stress e verifica aggregata del percorso | 300/300 richieste, 0 errori; suite, build, lint e security check verdi |

### Misure prima/dopo

Baseline del tratto Python misurata prima del ciclo, con client prewarmed:
0,198 ms mediana su un blocco, 0,208 ms su 8 blocchi e 0,237 ms su 64
blocchi. Dopo i 20 round, su 100 iterazioni sequenziali: 0,176 ms, 0,176 ms
e 0,232 ms rispettivamente. Il percorso a un blocco riduce quindi la mediana
misurata di circa l'11%; il caso lungo resta sostanzialmente invariato entro
il rumore del benchmark.

La suite finale conta 72 test Python; `cargo fmt --check`, `cargo clippy
-- -D warnings`, `cargo test` (10 unit test Rust e doctest), `py_compile`,
`npm run build`, `npm audit --omit=dev --audit-level=high` e `git diff --check`
sono passati. Il benchmark payload mantiene 128.573 byte identici prima/dopo
e lo stress cloud ha prodotto 300 risultati su 300 senza errori.

Nessun commit, branch secondario o push è stato eseguito.

## Hardening post-review end-to-end

- Cattura audio e processamento cloud/local sono stati separati in due worker:
  una nuova registrazione non resta accodata dietro una richiesta Groq ancora
  in corso.
- Aggiunta una regressione per il riavvio cloud rapido stop → start → stop.
- Aggiornamenti statistiche e `clear_history` condividono una coda ordinata;
  il clear è una barriera tra scritture precedenti e successive.
- Cronologia, salvataggi, letture e cancellazioni condividono una coda ordinata;
  un salvataggio precedente non può ricomparire dopo la cancellazione.
- Gli errori del motore emettono nuovamente `ready` e il renderer libera il
  lock di registrazione anche quando riceve `error`.
- Ripristinato il margine clipboard Windows a 50 ms per evitare race con le
  applicazioni target più lente.
- Polling hotkey riportato a 8 ms: resta reattivo senza il costo idle del
  polling a 250 Hz.

Verifica post-hardening: 72 test Python, build TypeScript/Vite e test mirato
stop → nuova registrazione superati.
