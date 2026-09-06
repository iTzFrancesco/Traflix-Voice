# Ricerca: Wispr Flow su mobile e piano Android per Traflix Voice

Data della ricerca: 6 settembre 2026 UTC
Ambito: fonti ufficiali Wispr, Google Play, Google Play policy e Android Developers.
Stato Traflix: implementazione preview su
[`feat/android-mobile-ime`](https://github.com/iTzFrancesco/Traflix-Voice/tree/feat/android-mobile-ime).
Il codice applicativo Android è in `src/mobile/` e `src-tauri/gen/android/`;
la decisione di merge è in
[`docs/android-merge-readiness.md`](../android-merge-readiness.md).

## Sintesi decisionale

Wispr Flow su Android non sostituisce la tastiera. Mostra una bolla flottante sopra la tastiera esistente quando l'utente entra in un campo di testo, registra la voce, invia l'audio al cloud e inserisce il risultato nel campo attivo tramite un Accessibility Service. La stessa azienda dichiara che Android 13 o versioni successive sono richieste, che il servizio non funziona offline e che alcuni campi o app vengono esclusi intenzionalmente. Vedi [pagina Android di Wispr Flow](https://wisprflow.ai/android), [guida di setup](https://docs.wisprflow.ai/articles/8858845757-setup-wispr-flow-on-android-android-settings) e [scheda Google Play](https://play.google.com/store/apps/details?id=com.wispr.flowapp).

Per Traflix, la scelta consigliata è diversa:

1. creare una vera Android IME, cioè una tastiera selezionabile dall'utente, con un tasto microfono;
2. usare l'`InputConnection` fornita dall'editor attivo per inserire il testo;
3. usare `RECORD_AUDIO` e, quando necessario, un foreground service di tipo `microphone` per la cattura;
4. usare il cloud solo per trascrivere e, se richiesto, ripulire la dettatura;
5. usare clipboard o Accessibility Service soltanto come fallback esplicito e non come percorso principale.

Questa scelta soddisfa il requisito "premere il pulsante microfono nella tastiera" senza chiedere all'app di disegnare sopra le altre app o di leggere la gerarchia delle loro schermate. Il compromesso è che l'utente deve abilitare e selezionare Traflix Keyboard nelle impostazioni Android. Android documenta esattamente questo modello per le tastiere e anche per gli IME speech-to-text: [Create an input method](https://developer.android.com/develop/ui/views/touch-and-input/creating-input-method).

Le affermazioni sulla UX di Wispr qui sotto sono una ricostruzione documentale. Non ho installato l'APK né eseguito un test su dispositivo, quindi non le presento come misurazioni indipendenti.

## Cosa fa davvero Wispr Flow su Android

### Modello di interazione

La UX ufficialmente documentata è questa:

1. L'utente apre un'app con un campo di testo e tocca il campo. La tastiera di sistema deve essere visibile.
2. Flow mostra la Flow Bubble sul bordo dello schermo.
3. Un tocco avvia una sessione hands-free. L'utente tocca il segno di spunta per terminare, oppure attende la fine della trascrizione.
4. Una pressione prolungata attiva il push-to-talk. Il rilascio termina la registrazione e avvia l'elaborazione.
5. Il testo viene inserito alla posizione del cursore. Se l'inserimento diretto fallisce, Flow espone un'azione Paste o Copy per recuperare il testo.

Questi passaggi sono descritti nelle guide [Starting Your First Dictation on Android](https://docs.wisprflow.ai/articles/2296441257-starting-your-first-dictation-on-android), [Setup Wispr Flow on Android](https://docs.wisprflow.ai/articles/8858845757-setup-wispr-flow-on-android-android-settings) e [Navigating the Wispr Flow App](https://docs.wisprflow.ai/articles/5096240724-navigating-the-wispr-flow-app-desktop-ios-and-android).

La bolla può essere spostata sul bordo sinistro o destro, ridotta a un punto dopo un periodo di inattività, ridotta nei campi di ricerca e messa in pausa per dieci minuti trascinandola verso il fondo dello schermo. Durante la dettatura torna alla dimensione completa. Queste funzioni sono documentate in [Customize Flow Bubble Size and Shrink Behavior](https://docs.wisprflow.ai/articles/2807859589-customize-flow-bubble-size-and-shrink-behavior-on-android) e [Using Wispr Flow Discreetly](https://docs.wisprflow.ai/articles/9192039587-using-wispr-flow-discreetly-microphone-guide).

Flow non offre su Android un trigger vocale hands-free e non offre lo Scratch Pad mobile. La sessione di dettatura è limitata a cinque minuti, con avvisi prima e al raggiungimento del limite. Offline la bolla diventa inattiva e la dettatura è bloccata. Fonte: [Using Wispr Flow Discreetly](https://docs.wisprflow.ai/articles/9192039587-using-wispr-flow-discreetly-microphone-guide).

### Onboarding e permessi

L'onboarding Android documentato da Wispr comprende:

- accesso con account;
- permesso "Display over other apps" per mostrare la bolla;
- permesso Accessibility Service per rilevare il campo e inserire il testo nelle altre app;
- scelta di privacy relativa all'uso dei dati per migliorare i modelli;
- permesso microfono richiesto alla prima pressione della bolla;
- esclusione dall'ottimizzazione batteria per mantenere il servizio disponibile in background;
- notifiche per avvisi su errori, connettività, limiti e stato del servizio.

La sequenza e i testi di setup sono riportati in [Setup Wispr Flow on Android](https://docs.wisprflow.ai/articles/8858845757-setup-wispr-flow-on-android-android-settings) e nella [Android Download & Installation Guide](https://docs.wisprflow.ai/articles/2809924024-android-download-installation-guide). La guida specifica che la bolla resta nascosta fino alla fine dell'onboarding e che le istruzioni aggiuntive cambiano in base al produttore.

Wispr segnala infatti problemi possibili con la gestione aggressiva della batteria e con la revoca silenziosa dell'accessibilità su Samsung, Xiaomi, OnePlus, OPPO, Vivo, Realme, Huawei, Honor, Motorola e altri produttori. La guida [Starting Your First Dictation on Android](https://docs.wisprflow.ai/articles/2296441257-starting-your-first-dictation-on-android) elenca per produttore autostart, esclusione batteria e blocco dell'app nei recenti.

### Dove appare e dove non appare

Wispr dichiara che Flow funziona nella maggior parte dei campi Android standard e non installa o sostituisce la tastiera. Non supporta in modo uniforme i sistemi di input personalizzati. La scheda Play lo riassume come "works in most apps that use standard Android text fields" e la pagina Android di Wispr precisa che una piccola parte delle app con sistemi di input custom può non essere supportata.

Le esclusioni documentate sono rilevanti per il progetto:

- niente bolla o inserimento in campi password, PIN, numerici e telefonici;
- bolla nascosta nelle app bancarie e finanziarie incluse nella lista interna di Flow;
- inserimento meno affidabile in editor web, app di messaggistica che non comunicano bene cursore e contenuto, address bar di alcuni browser e schermate di sistema;
- se il campo perde il focus, il risultato può non arrivare nel punto atteso;
- in alcuni casi il testo viene copiato negli appunti per un paste manuale.

Fonti: [Fix text not pasting after dictation](https://docs.wisprflow.ai/articles/7971211038-fix-text-not-pasting-after-dictation), [Reliable text insertion in messaging apps on Android](https://docs.wisprflow.ai/articles/2354103297-reliable-text-insertion-in-messaging-apps-on-android-whatsapp-telegram-messenger-signal-slack) e [Banking App Detection Support](https://docs.wisprflow.ai/articles/4909908692-banking-app-detection-support-in-wispr-flow).

Le pagine Wispr non sono perfettamente uniformi sulla Chrome address bar: la pagina Android la elenca tra i campi coperti, mentre la guida di troubleshooting segnala che Chrome può richiedere il paste manuale. La decisione prudente è quindi trattare le address bar e gli editor custom come casi di fallback, non come garanzia di inserimento diretto.

## Come viene inserito il testo

### Percorso Wispr osservabile dalle fonti

La scheda Google Play dichiara che Flow usa un Android Accessibility Service perché Android non offre a una normale app un'API standard per rilevare il focus dei campi e inserire testo in altre app. Wispr descrive l'uso del servizio per:

- rilevare i campi di testo e i cambi di focus;
- mostrare o nascondere la bolla;
- inserire la trascrizione nel campo attivo;
- gestire diagnostica e crash logging limitati.

Fonte primaria: [scheda Wispr Flow su Google Play](https://play.google.com/store/apps/details?id=com.wispr.flowapp), sezione "Accessibility Service Disclosure".

La guida Wispr per le app di messaggistica conferma che l'inserimento dipende dall'accessibilità e che il risultato può finire in posizione errata quando l'app non comunica correttamente cursore e contenuto. Se l'inserimento diretto non riesce, Flow copia il testo negli appunti per il paste manuale. Fonte: [Reliable text insertion in messaging apps on Android](https://docs.wisprflow.ai/articles/2354103297-reliable-text-insertion-in-messaging-apps-on-android-whatsapp-telegram-messenger-signal-slack).

### Modello Android preferibile per Traflix: IME e InputConnection

Android definisce un IME come un'applicazione con un servizio `InputMethodService`. Il sistema lo collega all'editor che ha il focus e gli fornisce una `InputConnection`. L'IME può essere una tastiera, un'interfaccia di scrittura a mano, una palette emoji oppure un motore speech-to-text. L'utente abilita e seleziona l'IME nelle impostazioni di sistema. Fonte: [Create an input method](https://developer.android.com/develop/ui/views/touch-and-input/creating-input-method).

L'`InputConnection` è il canale tra IME ed editor. L'API ufficiale include:

- `setComposingText()` per aggiornare una porzione provvisoria mentre la trascrizione sta arrivando;
- `finishComposingText()` per chiudere la composizione;
- `commitText()` per inserire il testo finale e posizionare il cursore;
- `deleteSurroundingText()` e lettura del testo vicino al cursore per correzioni mirate.

Fonte: [InputConnection API reference](https://developer.android.com/reference/android/view/inputmethod/InputConnection). Android documenta inoltre che `EditorInfo` comunica all'IME il tipo del campo, per esempio testo libero, numero, URL, telefono o password. Fonte: [Create an input method](https://developer.android.com/develop/ui/views/touch-and-input/creating-input-method).

Il flusso consigliato per Traflix è quindi:

1. `onStartInputView()` salva il contesto dell'editor e legge `EditorInfo.inputType`.
2. Il tasto microfono avvia la sessione associata a quella `InputConnection`.
3. Eventuali parziali ricevuti dal cloud aggiornano una sola regione di composing text, senza creare duplicati.
4. Il risultato finale chiama `commitText()` e chiude la regione provvisoria.
5. `onFinishInput()` o un cambio di editor invalida la sessione; il testo non deve essere consegnato a un campo diverso da quello scelto dall'utente.

Gli ultimi due punti sono una decisione progettuale dedotta dai limiti descritti da Wispr e dalla semantica ufficiale di `InputConnection`. Non sono una promessa dell'API: editor custom o app difettose possono comunque comportarsi in modo diverso, quindi vanno testati.

### Perché non si può aggiungere un pulsante dentro Gboard

Un'app normale non può modificare la UI della tastiera di terze parti. Se il requisito è un pulsante microfono "dentro la tastiera", Traflix deve essere una propria IME, eventualmente minimale all'inizio, oppure deve chiedere all'utente di usare un'interfaccia esterna.

La bolla di Wispr è la seconda soluzione: resta sopra la tastiera esistente, ma non è un pulsante integrato nella tastiera. Replicarla richiede overlay e Accessibility Service. Per un'app generalista questo porta più permessi, più casi OEM e più obblighi di policy rispetto a una IME nativa.

## Permessi e vincoli Android

### Microfono

La cattura richiede `android.permission.RECORD_AUDIO`, che è un permesso pericoloso e deve essere richiesto a runtime da Android 6 in poi. Android 12 mostra inoltre un indicatore di privacy quando un'app usa il microfono. Fonti: [MediaRecorder overview](https://developer.android.com/media/platform/mediarecorder) e [Request runtime permissions](https://developer.android.com/training/permissions/requesting).

Su Android 9 e versioni successive un'app in background non può accedere al microfono senza un foreground service. Fonte: [MediaRecorder overview](https://developer.android.com/media/platform/mediarecorder).

Se la registrazione può continuare mentre la UI della tastiera viene nascosta, il piano deve prevedere un servizio con:

- `android:foregroundServiceType="microphone"`;
- `FOREGROUND_SERVICE`;
- `FOREGROUND_SERVICE_MICROPHONE` per target Android 14 o successivi;
- `RECORD_AUDIO` concesso dall'utente;
- notifica visibile durante la cattura.

Fonti: [Foreground service types](https://developer.android.com/develop/background-work/services/fgs/service-types), [Declare foreground services and request permissions](https://developer.android.com/develop/background-work/services/fgs/declare) e [Launch a foreground service](https://developer.android.com/develop/background-work/services/fgs/launch).

Android consente a un'app che è l'IME corrente di avviare un foreground service in alcuni scenari di background, ma le regole Android 14 sulle permission while-in-use del microfono restano un vincolo da verificare su dispositivo. Il tap sul microfono deve essere l'azione utente che avvia la registrazione; il test deve includere Android 14 e versioni successive. Fonte: [Restrictions on starting a foreground service from the background](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start).

### Tastiera e campo attivo

L'IME deve dichiarare il servizio con `BIND_INPUT_METHOD`, il filtro `android.view.InputMethod` e i metadata dell'input method. Non è un normale permesso runtime, ma l'utente deve abilitare e selezionare la tastiera. Fonte: [Create an input method](https://developer.android.com/develop/ui/views/touch-and-input/creating-input-method).

L'IME deve rispettare `EditorInfo.inputType` e non inviare dettatura cloud a campi sensibili per default. Android documenta esplicitamente i tipi password, numero, telefono, URL e testo libero. Per Traflix il comportamento iniziale consigliato è:

- disabilitare il microfono per password, PIN, numeri di pagamento e telefono;
- consentire testo libero, email, URL e ricerca con una policy chiara;
- mostrare un motivo comprensibile quando il pulsante è disabilitato;
- non caricare il contenuto circostante al campo salvo una scelta esplicita dell'utente.

### Foreground service e notifiche

Android 13 introduce `POST_NOTIFICATIONS`. La sua negazione non impedisce di avviare un foreground service, ma nasconde la notifica nel pannello mentre il servizio resta visibile nel Task Manager. Fonte: [Notification runtime permission](https://developer.android.com/develop/ui/compose/notifications/notification-permission).

La notifica deve spiegare che Traflix sta registrando e deve offrire Stop. Non va usata per nascondere una cattura lunga o per mantenere il microfono aperto dopo la fine della sessione.

### Overlay e Accessibility Service, se si sceglie il modello Wispr

Un overlay applicativo usa `TYPE_APPLICATION_OVERLAY` e richiede `SYSTEM_ALERT_WINDOW`; il sistema può ridurne posizione, dimensione o visibilità e Android 12 applica regole contro i touch che passano attraverso overlay non affidabili. Fonte: [WindowManager.LayoutParams](https://developer.android.com/reference/android/view/WindowManager.LayoutParams).

Un Accessibility Service può ricevere eventi, ispezionare la finestra attiva se configurato con `canRetrieveWindowContent` e compiere azioni sui nodi, incluso `ACTION_SET_TEXT` quando l'app target lo supporta. Fonti: [Create your own accessibility service](https://developer.android.com/guide/topics/ui/accessibility/views/service) e [AccessibilityNodeInfo](https://developer.android.com/reference/android/view/accessibility/AccessibilityNodeInfo).

Google Play richiede però che un Accessibility Service sia usato per una funzione stretta e dichiarata. Il flag `isAccessibilityTool` è destinato ad app il cui scopo principale è aiutare persone con disabilità; un assistente generalista che aiuta anche utenti con disabilità non rientra automaticamente in questa categoria. Gli altri casi richiedono disclosure prominente nell'app, consenso affermativo e dichiarazione Play. Fonte: [Use of the AccessibilityService API](https://support.google.com/googleplay/android-developer/answer/10964491?hl=en).

Per questo il percorso overlay + Accessibility Service va tenuto come alternativa di prodotto, non come architettura MVP, a meno che Traflix non venga posizionato e documentato come vero strumento di input assistivo.

### Clipboard

Android espone la clipboard globale tramite `ClipboardManager`, `setPrimaryClip()` e `getPrimaryClip()`. La documentazione segnala che lettura e presenza della clip possono restituire `null` o `false` quando l'app non è l'IME predefinito o non ha il focus di input. Fonte: [ClipboardManager](https://developer.android.com/reference/android/content/ClipboardManager).

Da Android 13 il sistema mostra una conferma visiva quando un'app copia contenuto, con anteprima della clip. Fonte: [Android 13 features and changes](https://developer.android.com/about/versions/13/features).

La clipboard non deve quindi essere il percorso normale di Traflix. Va usata solo dopo un fallimento esplicito dell'`InputConnection`, con un'azione Copy o Paste avviata dall'utente, senza sovrascrivere e poi ripristinare automaticamente il contenuto precedente.

## Privacy e cloud di Wispr Flow

Wispr dichiara che la trascrizione avviene sempre nel cloud e che Flow non funziona offline. La pagina Data Controls distingue due decisioni:

- "Improve the model for everyone": controlla se audio, trascrizioni e modifiche possono essere usati per valutare, addestrare o migliorare i modelli;
- "Dictation Cloud Storage": controlla se trascrizioni, audio e cronologia vengono conservati sui server per funzioni persistenti e cross-device.

Wispr dichiara inoltre di non vendere i dati, di cifrare i dati in transito e a riposo e di avere accordi di zero data retention con i provider AI terzi usati per la dettatura. Fonti: [Data Controls](https://wisprflow.ai/data-controls) e [Privacy](https://wisprflow.ai/privacy).

La Privacy Policy aggiunge che l'azienda può trattare audio con informazioni personali, dati di utilizzo inclusa l'app usata per la dettatura e, se l'utente abilita Context Awareness, contenuto rilevante dell'app attiva. Dichiara anche l'uso di provider terzi per fornire alcune funzioni e una cancellazione generalmente entro 30 giorni per i contenuti forniti a terzi, con le eccezioni indicate nella policy. Fonte: [Privacy Policy](https://wisprflow.ai/privacy-policy).

La scheda Google Play riporta, come informazione dichiarata dallo sviluppatore, che l'app può raccogliere dati personali e audio, può condividere categorie di dati con terzi, cifra i dati in transito e consente di chiedere la cancellazione. La sezione Play è una dichiarazione del developer e può cambiare per versione, regione o aggiornamento. Fonte: [Wispr Flow su Google Play](https://play.google.com/store/apps/details?id=com.wispr.flowapp).

Per Traflix il consenso deve essere più esplicito possibile:

1. mostrare prima della prima registrazione che l'audio lascia il dispositivo;
2. separare "trascrivi nel cloud" da "conserva cronologia/audio" e da "usa per migliorare il modello";
3. impostare il training su off come default di prodotto, salvo decisione contraria documentata;
4. specificare provider, regione di trattamento, cifratura, retention, cancellazione e gestione degli errori;
5. non inviare il nome dell'app attiva, testo vicino al cursore o contenuto del campo se non servono al servizio e non sono stati autorizzati;
6. non registrare audio dopo Stop, perdita del focus o revoca del permesso;
7. non conservare audio locale oltre il tempo necessario per un retry esplicito.

## Architettura proposta per Traflix Android

### Componenti

La prima versione dovrebbe avere questi componenti nativi Kotlin:

- `TraflixInputMethodService`: UI della tastiera, tasto microfono, modalità tap-to-toggle e press-to-talk, lifecycle dell'editor;
- `InputSession`: snapshot dell'editor, package name noto al sistema, `EditorInfo`, `InputConnection` e stato della sessione;
- `AudioCapture`: `AudioRecord` o API equivalente, con livello, route microfono e stop immediato;
- `RecordingService`: foreground service solo quando necessario per continuare la cattura fuori dalla UI visibile;
- `CloudTranscriptionClient`: upload o streaming autenticato, timeout, retry limitato e cancellazione;
- `InsertionController`: composing text, commit finale, invalidazione su cambio campo e fallback Copy;
- `TraflixApp`: onboarding, login, impostazioni, privacy, cronologia locale e diagnostica senza audio nei log;
- storage locale cifrato per token e preferenze. Audio e trascrizioni devono essere cancellabili e avere retention configurabile.

### Sequenza end-to-end

```text
Campo attivo
    -> Traflix IME riceve InputConnection
    -> tap microfono / pressione prolungata
    -> controllo tipo campo e RECORD_AUDIO
    -> AudioRecord + indicatore IME/notifica
    -> audio temporaneo o stream TLS verso API cloud
    -> trascrizione e normalizzazione lato server
    -> parziali con setComposingText, se il contratto li supporta
    -> finale con commitText
    -> stop, pulizia audio, cronologia secondo policy
```

Il server deve restituire almeno `request_id`, stato, testo parziale opzionale, testo finale, lingua rilevata o selezionata, durata e codice errore senza includere la chiave API nei log. Il contratto mobile deve essere versionato e idempotente: un retry non deve inserire due volte lo stesso testo.

### Decisioni UX da prendere prima di implementare

- **Tastiera completa o tastiera minimale:** per l'MVP una tastiera minimale con tasto microfono e tasto per passare alla tastiera precedente riduce il lavoro, ma la tastiera completa offre un'esperienza autonoma. Android raccomanda di fornire un modo per cambiare IME direttamente dalla UI.
- **Tap o hold:** offrire entrambi. Il tap è adatto a dettati lunghi; il hold riduce registrazioni accidentali nei messaggi brevi. È lo stesso compromesso che Wispr espone nella sua guida.
- **Parziali o solo finale:** partire con solo finale se la latenza cloud non è ancora affidabile. Aggiungere `setComposingText` quando il server può garantire aggiornamenti ordinati e sostituibili.
- **Offline:** mostrare subito "Connessione necessaria" e non registrare, oppure implementare una coda cifrata per retry. Wispr sceglie il blocco offline, ma Traflix deve decidere esplicitamente.
- **Campi sensibili:** disattivare il microfono per password, PIN e numeri sensibili. Non tentare di aggirare `inputType` con Accessibility o clipboard.
- **Cambio app durante l'elaborazione:** annullare l'inserimento automatico e lasciare il risultato in una cronologia locale con Copy. È più sicuro che incollare nel nuovo campo attivo.

## Piano di realizzazione

### Fase 0: decisione e prototipo di rischio

Obiettivo: validare il percorso IME prima di costruire account e cloud.

- creare una IME di prova con un pulsante;
- inserire una stringa fissa tramite `commitText` in EditText, Chrome, Gmail/Google Keep e un'app di messaggistica;
- verificare `onStartInputView`, `onFinishInput`, cambio tastiera e campi password/numerici;
- testare Android 13, 14 e 15 o versioni disponibili sui device reali;
- decidere se l'MVP richiede un foreground service durante la sola cattura.

Gate: il testo arriva una volta sola nel campo originale dopo tap, rotazione, cambio app e perdita del focus.

### Fase 1: shell Android e onboarding

- app nativa Android con Kotlin e UI di onboarding;
- registrazione dell'IME nel manifest;
- guida per abilitare e selezionare la tastiera;
- login e gestione token senza segreti nel codice;
- richiesta incrementale di microfono e notifiche;
- schermata privacy prima della prima registrazione;
- diagnostica di permessi con messaggi riparabili.

Gate: un utente nuovo può arrivare al campo di prova senza istruzioni esterne e può revocare ogni permesso senza crash.

### Fase 2: cattura locale

- tap-to-toggle e press-to-talk;
- audio PCM con formato definito dal contratto cloud;
- timer, stato recording/processing/error;
- stop su cancellazione, revoca del microfono, `onFinishInput` e perdita della connessione;
- foreground service di tipo microfono dove richiesto;
- notifica con Stop e nessun log audio.

Gate: il microfono si apre solo dopo azione utente, l'indicatore Android è coerente e ogni sessione termina rilasciando il dispositivo audio.

### Fase 3: cloud transcription

- endpoint autenticato con upload streaming o file temporaneo;
- limite dimensionale e durata, rate limit e timeout;
- lingua scelta nell'app, con fallback esplicito;
- testo normalizzato e punteggiatura;
- errori separati per offline, permesso, quota, rete, provider e inserimento;
- retry idempotente e niente doppio commit.

Gate: testo finale con latenza e tasso di errore misurati su rete Wi-Fi, rete mobile e perdita di rete durante upload.

### Fase 4: inserimento affidabile

- composing text solo se i parziali sono ordinati;
- commit finale con `commitText`;
- controllo del tipo campo tramite `EditorInfo`;
- invalidazione dell'`InputConnection` quando cambia l'editor;
- Copy manuale come fallback, con avviso sul comportamento della clipboard;
- cronologia locale separata dal cloud e cancellazione esplicita.

Gate: test automatici dell'`InsertionController` e test manuali su app standard, editor web, password, numeri, messaggi e app bancarie.

### Fase 5: hardening e pubblicazione

- privacy policy, Data Safety e disclosure Play coerenti con dati e SDK reali;
- audit delle richieste di permesso e dei log;
- test su Pixel/stock Android, Samsung, Xiaomi/Redmi/POCO, OnePlus, OPPO, Vivo e Motorola;
- test con Bluetooth, cuffie cablate, rotazione, schermo bloccato, modalità risparmio batteria e cambio IME;
- test API 34+ del foreground service e dei casi di avvio da IME;
- verifica di cancellazione account, retention, token e audio temporanei;
- distribuzione interna prima della release pubblica.

## Acceptance criteria dell'MVP

- L'utente può installare l'APK, abilitare Traflix Keyboard e sceglierla per un campo di testo.
- Il tasto microfono avvia e ferma la registrazione senza overlay o Accessibility Service.
- L'audio raggiunge il backend solo con `RECORD_AUDIO` concesso e dopo un'azione utente.
- Il testo cloud viene inserito nel campo attivo tramite `InputConnection`, senza usare clipboard come percorso primario.
- Se la connessione o l'inserimento falliscono, il testo non viene perso: appare nella cronologia locale e può essere copiato con un'azione dell'utente.
- Password, PIN e campi sensibili non inviano audio.
- Stop, revoca permesso, cambio campo e cambio app interrompono o invalidano la sessione.
- Nessun audio, testo dettato, token o chiave viene scritto nei log.
- L'app spiega chiaramente che la trascrizione è cloud e permette di cancellare audio temporanei, risultati locali e account secondo la policy scelta.

## Fonti primarie consultate

### Wispr Flow

- [Flow for Android](https://wisprflow.ai/android)
- [Wispr Flow su Google Play](https://play.google.com/store/apps/details?id=com.wispr.flowapp)
- [Setup Wispr Flow on Android](https://docs.wisprflow.ai/articles/8858845757-setup-wispr-flow-on-android-android-settings)
- [Android Download & Installation Guide](https://docs.wisprflow.ai/articles/2809924024-android-download-installation-guide)
- [Starting Your First Dictation on Android](https://docs.wisprflow.ai/articles/2296441257-starting-your-first-dictation-on-android)
- [Navigating the Wispr Flow App](https://docs.wisprflow.ai/articles/5096240724-navigating-the-wispr-flow-app-desktop-ios-and-android)
- [Customize Flow Bubble Size and Shrink Behavior](https://docs.wisprflow.ai/articles/2807859589-customize-flow-bubble-size-and-shrink-behavior-on-android)
- [Using Wispr Flow Discreetly](https://docs.wisprflow.ai/articles/9192039587-using-wispr-flow-discreetly-microphone-guide)
- [Fix text not pasting after dictation](https://docs.wisprflow.ai/articles/7971211038-fix-text-not-pasting-after-dictation)
- [Reliable text insertion in messaging apps](https://docs.wisprflow.ai/articles/2354103297-reliable-text-insertion-in-messaging-apps-on-android-whatsapp-telegram-messenger-signal-slack)
- [Banking App Detection Support](https://docs.wisprflow.ai/articles/4909908692-banking-app-detection-support-in-wispr-flow)
- [Data Controls](https://wisprflow.ai/data-controls)
- [Privacy](https://wisprflow.ai/privacy)
- [Privacy Policy](https://wisprflow.ai/privacy-policy)

### Android e Google Play

- [Create an input method](https://developer.android.com/develop/ui/views/touch-and-input/creating-input-method)
- [InputConnection API reference](https://developer.android.com/reference/android/view/inputmethod/InputConnection)
- [Request runtime permissions](https://developer.android.com/training/permissions/requesting)
- [MediaRecorder overview](https://developer.android.com/media/platform/mediarecorder)
- [Foreground service types](https://developer.android.com/develop/background-work/services/fgs/service-types)
- [Declare foreground services and request permissions](https://developer.android.com/develop/background-work/services/fgs/declare)
- [Launch a foreground service](https://developer.android.com/develop/background-work/services/fgs/launch)
- [Restrictions on starting a foreground service from the background](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start)
- [Notification runtime permission](https://developer.android.com/develop/ui/compose/notifications/notification-permission)
- [Create your own accessibility service](https://developer.android.com/guide/topics/ui/accessibility/views/service)
- [AccessibilityNodeInfo API reference](https://developer.android.com/reference/android/view/accessibility/AccessibilityNodeInfo)
- [WindowManager.LayoutParams API reference](https://developer.android.com/reference/android/view/WindowManager.LayoutParams)
- [ClipboardManager API reference](https://developer.android.com/reference/android/content/ClipboardManager)
- [Android 13 features and changes](https://developer.android.com/about/versions/13/features)
- [Google Play: Use of the AccessibilityService API](https://support.google.com/googleplay/android-developer/answer/10964491?hl=en)
