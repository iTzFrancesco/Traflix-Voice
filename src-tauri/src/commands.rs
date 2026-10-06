#[cfg(not(target_os = "android"))]
use cpal::traits::{DeviceTrait, HostTrait};
use log::info;
use std::fs;
use std::sync::{Arc, Mutex};
use tauri::{AppHandle, Emitter, Manager, Runtime, State};
use tauri_plugin_shell::process::CommandChild;

use crate::clipboard::simulate_ctrl_v;
use crate::hotkey::parse_hotkey;
use crate::settings::{atomic_write, ensure_app_data_dir, load_settings_from_file};
use crate::state::{
    AppSettings, AppState, AppStats, AudioDeviceInfo, GroqUsage, TranscriptionEntry,
};

// ─── COMANDI TAURI ───────────────────────────────────────────────────────────

#[tauri::command]
pub fn is_dev() -> bool {
    cfg!(debug_assertions)
}

/// Legge e restituisce le impostazioni salvate (o i valori di default)
#[tauri::command]
pub async fn load_settings(state: State<'_, AppState>) -> Result<AppSettings, String> {
    let settings = load_settings_from_file(&state.settings_path);
    info!(
        "[save-debug] load_settings: hotkey={}, hold_to_speak={}, provider={}, model={}, path={:?}",
        settings.hotkey,
        settings.hold_to_speak,
        settings.provider,
        settings.model,
        state.settings_path
    );
    Ok(settings)
}

/// Salva le impostazioni su disco e aggiorna la hotkey attiva
#[tauri::command]
pub async fn save_settings<R: Runtime>(
    app: AppHandle<R>,
    state: State<'_, AppState>,
    settings: AppSettings,
) -> Result<(), String> {
    ensure_app_data_dir(&state.settings_path);
    let data = serde_json::to_string_pretty(&settings).map_err(|e| e.to_string())?;
    info!(
        "[save-debug] save_settings WRITING: hotkey={}, hold_to_speak={}, widget_mode={}, data_len={}",
        settings.hotkey,
        settings.hold_to_speak,
        settings.widget_mode,
        data.len()
    );
    atomic_write(&state.settings_path, &data).map_err(|e| e.to_string())?;
    info!("[save-debug] save_settings WRITE OK");

    state.keep_clipboard_result.store(
        settings.keep_clipboard_result,
        std::sync::atomic::Ordering::Relaxed,
    );

    let new_configs = [settings.hotkey.as_str(), settings.secondary_hotkey.as_str()]
        .into_iter()
        .filter(|hotkey| !hotkey.trim().is_empty())
        .map(parse_hotkey)
        .filter(|config| !config.vk_codes.is_empty())
        .collect::<Vec<_>>();
    info!("[Hotkey] Aggiornate: {:?}", new_configs);
    *state.hotkey_config.write().unwrap() = new_configs;

    // Emit widget mode update for the overlay
    let _ = app.emit("widget_mode_updated", settings.widget_mode.clone());
    let _ = app.emit("cloud_provider_updated", settings.provider.clone());

    Ok(())
}

/// Aggiorna le statistiche e le salva su disco
#[tauri::command]
pub async fn update_stats(
    state: State<'_, AppState>,
    words: u32,
    _wpm: u32,
    time_delta: f32,
) -> Result<AppStats, String> {
    if !time_delta.is_finite() || time_delta < 0.0 {
        return Err("Durata trascrizione non valida".to_string());
    }

    // Serialize file snapshots without holding the short-lived stats mutex;
    // this keeps get_stats responsive while preserving write ordering.
    let _stats_write_guard = state.stats_write_lock.lock().unwrap();
    let updated_stats = {
        let mut stats = state.stats.lock().unwrap();
        stats.total_words += words;
        stats.total_time += time_delta;

        // total_time is in minutes, so WPM = total_words / total_time_in_minutes
        if stats.total_time > 0.0 {
            stats.avg_wpm = (stats.total_words as f32 / stats.total_time).round() as u32;
        }
        stats.clone()
    };

    ensure_app_data_dir(&state.stats_path);
    // Stats are machine-read JSON and are rewritten after every cloud result;
    // compact encoding reduces serialization and disk-write work.
    let data = serde_json::to_string(&updated_stats).map_err(|e| e.to_string())?;
    atomic_write(&state.stats_path, &data).map_err(|e| e.to_string())?;

    Ok(updated_stats)
}

/// Restituisce le statistiche correnti
#[tauri::command]
pub async fn get_stats(state: State<'_, AppState>) -> Result<AppStats, String> {
    // The native Android IME updates stats.json while the Hub process stays
    // alive. Refresh the in-memory snapshot so the mobile dashboard reflects
    // dictation sessions made outside the WebView.
    #[cfg(target_os = "android")]
    if let Ok(data) = fs::read_to_string(&state.stats_path) {
        if let Ok(stats) = serde_json::from_str::<AppStats>(&data) {
            *state.stats.lock().unwrap() = stats.clone();
            return Ok(stats);
        }
    }

    let stats = state.stats.lock().unwrap();
    Ok(stats.clone())
}

/// Restituisce i dispositivi audio disponibili
#[cfg(not(target_os = "android"))]
#[tauri::command]
pub async fn get_audio_devices() -> Result<Vec<AudioDeviceInfo>, String> {
    tauri::async_runtime::spawn_blocking(enumerate_audio_devices)
        .await
        .map_err(|error| error.to_string())?
}

#[cfg(not(target_os = "android"))]
fn enumerate_audio_devices() -> Result<Vec<AudioDeviceInfo>, String> {
    let host = cpal::default_host();
    let mut devices = Vec::new();
    let input_devices = host.input_devices().map_err(|e| e.to_string())?;
    for device in input_devices {
        if let Ok(name) = device.name() {
            devices.push(AudioDeviceInfo {
                id: name.clone(),
                name,
            });
        }
    }
    Ok(devices)
}

/// Android records through the native VoiceAudioRecorder instead of cpal.
#[cfg(target_os = "android")]
#[tauri::command]
pub async fn get_audio_devices() -> Result<Vec<AudioDeviceInfo>, String> {
    Ok(Vec::new())
}

/// Controlla se un modello esiste già su disco
#[tauri::command]
pub async fn check_model_exists(app: AppHandle, model_id: String) -> bool {
    tauri::async_runtime::spawn_blocking(move || model_exists(app, model_id))
        .await
        .unwrap_or(false)
}

fn model_exists(app: AppHandle, model_id: String) -> bool {
    let app_dir = app.path().app_data_dir().unwrap_or_default();
    let dir = app_dir.join("models").join(&model_id);
    [
        "encoder.int8.onnx",
        "decoder.int8.onnx",
        "joiner.int8.onnx",
        "tokens.txt",
    ]
    .iter()
    .all(|f| dir.join(f).exists())
}

/// Invia un comando al processo Python
#[tauri::command]
pub async fn send_to_python(state: State<'_, AppState>, message: String) -> Result<(), String> {
    let _write_guard = state.python_write_lock.lock().await;
    let python_process = Arc::clone(&state.python_process);
    let mut payload = message.into_bytes();
    payload.push(b'\n');
    tauri::async_runtime::spawn_blocking(move || write_to_python(&python_process, &payload))
        .await
        .map_err(|error| error.to_string())?
}

/// Fast path for the most latency-sensitive command in the recording flow.
#[tauri::command]
pub async fn stop_python(state: State<'_, AppState>) -> Result<(), String> {
    let _write_guard = state.python_write_lock.lock().await;
    let python_process = Arc::clone(&state.python_process);
    tauri::async_runtime::spawn_blocking(move || {
        write_to_python(&python_process, b"{\"command\":\"stop\"}\n")
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
pub async fn shutdown_python<R: Runtime>(app: AppHandle<R>) -> Result<(), String> {
    #[cfg(desktop)]
    {
        let write_lock = Arc::clone(&app.state::<AppState>().python_write_lock);
        let _write_guard = write_lock.lock().await;
        tauri::async_runtime::spawn_blocking(move || crate::sidecar::shutdown(&app))
            .await
            .map_err(|error| error.to_string())?
    }

    #[cfg(not(desktop))]
    {
        let _ = app;
        Ok(())
    }
}

#[tauri::command]
pub fn restart_app<R: Runtime>(app: AppHandle<R>) {
    app.restart();
}

fn write_to_python(
    python_process: &Mutex<Option<CommandChild>>,
    payload: &[u8],
) -> Result<(), String> {
    let mut process_lock = python_process.lock().unwrap();
    if let Some(child) = process_lock.as_mut() {
        child.write(payload).map_err(|e| e.to_string())?;
        Ok(())
    } else {
        Err("Motore Python non avviato".to_string())
    }
}

/// Copia il testo negli appunti e simula Ctrl+V.
///
/// Con `keepClipboardResult` disattivo il contenuto precedente degli appunti
/// viene ripristinato dopo il paste; se è attivo la trascrizione resta negli
/// appunti, così l'utente può recuperarla con Ctrl+V in un secondo momento.
#[tauri::command]
pub async fn execute_paste<R: Runtime>(
    app: AppHandle<R>,
    state: State<'_, AppState>,
    text: String,
) -> Result<(), String> {
    use std::{thread, time::Duration};
    use tauri_plugin_clipboard_manager::ClipboardExt;

    let previous = if state
        .keep_clipboard_result
        .load(std::sync::atomic::Ordering::Relaxed)
    {
        None
    } else {
        app.clipboard().read_text().ok()
    };

    app.clipboard()
        .write_text(text)
        .map_err(|e| e.to_string())?;

    // Keep a conservative settle window for slower Windows target apps. The
    // clipboard write is synchronous, but SendInput can otherwise race a
    // target that has not observed the new clipboard sequence yet.
    thread::sleep(Duration::from_millis(50));

    if !simulate_ctrl_v() {
        return Err(
            "Incolla automatico non riuscito; il testo è rimasto negli appunti".to_string(),
        );
    }

    if let Some(prev) = previous {
        thread::sleep(Duration::from_millis(100));
        let _ = app.clipboard().write_text(prev);
    }

    Ok(())
}

// ─── COMANDI CRONOLOGIA ──────────────────────────────────────────────────────

/// Salva una trascrizione nella cronologia (history.json)
#[tauri::command]
pub async fn save_transcription(
    state: State<'_, AppState>,
    text: String,
    timestamp: String,
    word_count: u32,
) -> Result<(), String> {
    let _history_guard = state.history_lock.lock().unwrap();
    ensure_app_data_dir(&state.history_path);

    let mut entries: Vec<TranscriptionEntry> =
        if let Ok(data) = fs::read_to_string(&state.history_path) {
            serde_json::from_str(&data).unwrap_or_default()
        } else {
            Vec::new()
        };

    entries.push(TranscriptionEntry {
        text,
        timestamp,
        word_count,
    });

    // Mantieni solo le ultime 50 voci
    if entries.len() > 50 {
        let remove_count = entries.len() - 50;
        entries.drain(..remove_count);
    }

    // History is machine-read JSON and is rewritten after every result; keep
    // the payload small while retaining the same schema and ordering.
    let data = serde_json::to_string(&entries).map_err(|e| e.to_string())?;
    atomic_write(&state.history_path, &data).map_err(|e| e.to_string())?;

    Ok(())
}

/// Restituisce la cronologia (ultime 50 trascrizioni, dalla più recente)
#[tauri::command]
pub async fn get_history(state: State<'_, AppState>) -> Result<Vec<TranscriptionEntry>, String> {
    let _history_guard = state.history_lock.lock().unwrap();
    if let Ok(data) = fs::read_to_string(&state.history_path) {
        let mut entries: Vec<TranscriptionEntry> = serde_json::from_str(&data).unwrap_or_default();
        entries.reverse(); // Più recente prima
        Ok(entries)
    } else {
        Ok(Vec::new())
    }
}

fn remove_history_entry(
    entries: &mut Vec<TranscriptionEntry>,
    newest_first_index: usize,
    target: &TranscriptionEntry,
) -> bool {
    let storage_index = match newest_first_index
        .checked_add(1)
        .and_then(|offset| entries.len().checked_sub(offset))
    {
        Some(index) => index,
        None => return false,
    };

    let matches_target = |entry: &TranscriptionEntry| {
        entry.text == target.text
            && entry.timestamp == target.timestamp
            && entry.word_count == target.word_count
    };

    if entries
        .get(storage_index)
        .map(matches_target)
        .unwrap_or(false)
    {
        entries.remove(storage_index);
        return true;
    }

    if let Some(index) = entries.iter().rposition(matches_target) {
        entries.remove(index);
        return true;
    }

    false
}

/// Cancella una singola trascrizione senza modificare le altre voci o le statistiche.
#[tauri::command]
pub async fn delete_history_entry(
    state: State<'_, AppState>,
    index: usize,
    text: String,
    timestamp: String,
    word_count: u32,
) -> Result<bool, String> {
    let _history_guard = state.history_lock.lock().unwrap();
    let data = match fs::read_to_string(&state.history_path) {
        Ok(data) => data,
        Err(_) => return Ok(false),
    };
    let mut entries: Vec<TranscriptionEntry> = serde_json::from_str(&data).unwrap_or_default();
    let target = TranscriptionEntry {
        text,
        timestamp,
        word_count,
    };

    if !remove_history_entry(&mut entries, index, &target) {
        return Ok(false);
    }

    let updated = serde_json::to_string(&entries).map_err(|e| e.to_string())?;
    atomic_write(&state.history_path, &updated).map_err(|e| e.to_string())?;
    Ok(true)
}

/// Cancella tutta la cronologia e resetta le statistiche
#[tauri::command]
pub async fn clear_history(state: State<'_, AppState>) -> Result<(), String> {
    let _history_guard = state.history_lock.lock().unwrap();
    let _stats_write_guard = state.stats_write_lock.lock().unwrap();
    if state.history_path.exists() {
        fs::remove_file(&state.history_path).map_err(|e| e.to_string())?;
    }
    let stats = {
        let mut current = state.stats.lock().unwrap();
        *current = AppStats::default();
        current.clone()
    };
    ensure_app_data_dir(&state.stats_path);
    let data = serde_json::to_string(&stats).map_err(|e| e.to_string())?;
    atomic_write(&state.stats_path, &data).map_err(|e| e.to_string())?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::remove_history_entry;
    use crate::state::TranscriptionEntry;

    fn entry(text: &str, timestamp: &str) -> TranscriptionEntry {
        TranscriptionEntry {
            text: text.to_string(),
            timestamp: timestamp.to_string(),
            word_count: 1,
        }
    }

    #[test]
    fn removes_entry_using_newest_first_index() {
        let oldest = entry("vecchia", "10:00");
        let middle = entry("centrale", "10:01");
        let newest = entry("recente", "10:02");
        let mut entries = vec![oldest.clone(), middle, newest.clone()];

        assert!(remove_history_entry(&mut entries, 0, &newest));
        assert_eq!(entries.len(), 2);
        assert_eq!(entries[0].text, oldest.text);
    }

    #[test]
    fn rejects_stale_entry_without_changing_history() {
        let stored = entry("salvata", "10:00");
        let mut entries = vec![stored];
        let missing = entry("non presente", "10:01");

        assert!(!remove_history_entry(&mut entries, 0, &missing));
        assert_eq!(entries.len(), 1);
    }
}

#[cfg(all(test, desktop))]
mod ipc_tests {
    use std::{
        path::PathBuf,
        sync::{
            atomic::AtomicBool,
            mpsc::{self, Receiver},
            Arc, Mutex, RwLock,
        },
        thread,
        time::Duration,
    };

    use tauri::{
        ipc::{CallbackFn, InvokeBody, InvokeResponse},
        test::{self, MockRuntime},
        webview::InvokeRequest,
        WebviewWindow, WebviewWindowBuilder,
    };

    use super::{send_to_python, shutdown_python, stop_python};
    use crate::state::{AppState, AppStats, HotkeyConfig};

    fn request(command: &str, body: serde_json::Value) -> InvokeRequest {
        InvokeRequest {
            cmd: command.to_string(),
            callback: CallbackFn(0),
            error: CallbackFn(1),
            url: "http://tauri.localhost".parse().unwrap(),
            body: InvokeBody::Json(body),
            headers: Default::default(),
            invoke_key: test::INVOKE_KEY.to_string(),
        }
    }

    #[tauri::command]
    fn ping() -> &'static str {
        "pong"
    }

    fn test_app(
        python_process: Arc<Mutex<Option<tauri_plugin_shell::process::CommandChild>>>,
        python_process_exited: bool,
    ) -> (tauri::App<MockRuntime>, WebviewWindow<MockRuntime>) {
        let state = AppState {
            stats: Mutex::new(AppStats::default()),
            stats_write_lock: Mutex::new(()),
            python_process,
            python_write_lock: Arc::new(tauri::async_runtime::Mutex::new(())),
            settings_path: PathBuf::new(),
            stats_path: PathBuf::new(),
            history_path: PathBuf::new(),
            history_lock: Mutex::new(()),
            groq_usage_path: PathBuf::new(),
            hotkey_config: Arc::new(RwLock::new(Vec::<HotkeyConfig>::new())),
            keep_clipboard_result: AtomicBool::new(true),
            is_shutting_down: AtomicBool::new(false),
            python_process_exited: AtomicBool::new(python_process_exited),
        };
        let app = test::mock_builder()
            .manage(state)
            .invoke_handler(tauri::generate_handler![
                send_to_python,
                stop_python,
                shutdown_python,
                ping
            ])
            .build(test::mock_context(test::noop_assets()))
            .unwrap();
        let window = WebviewWindowBuilder::new(&app, "main", Default::default())
            .build()
            .unwrap();
        (app, window)
    }

    fn dispatch_without_blocking(
        window: &WebviewWindow<MockRuntime>,
        command: &str,
        body: serde_json::Value,
    ) -> Receiver<InvokeResponse> {
        let (dispatched_tx, dispatched_rx) = mpsc::sync_channel(1);
        let (response_tx, response_rx) = mpsc::sync_channel(1);
        let webview = window.as_ref().clone();
        let command = command.to_string();
        thread::spawn(move || {
            webview.on_message(
                request(&command, body),
                Box::new(move |_webview, _command, response, _callback, _error| {
                    let _ = response_tx.send(response);
                }),
            );
            let _ = dispatched_tx.send(());
        });
        dispatched_rx
            .recv_timeout(Duration::from_secs(1))
            .expect("IPC dispatch blocked while the sidecar worker was stalled");
        response_rx
    }

    #[test]
    fn stalled_sidecar_writes_do_not_block_other_window_ipc() {
        let python_process = Arc::new(Mutex::new(None));
        let process_guard = python_process.lock().unwrap();
        let (_app, window) = test_app(Arc::clone(&python_process), true);

        let send_response = dispatch_without_blocking(
            &window,
            "send_to_python",
            serde_json::json!({"message": "{\"command\":\"get_status\"}"}),
        );
        let stop_response =
            dispatch_without_blocking(&window, "stop_python", serde_json::json!({}));

        test::assert_ipc_response(&window, request("ping", serde_json::json!({})), Ok("pong"));

        drop(process_guard);
        for response in [send_response, stop_response] {
            match response.recv_timeout(Duration::from_secs(1)).unwrap() {
                InvokeResponse::Err(error) => assert_eq!(
                    error.0,
                    serde_json::Value::String("Motore Python non avviato".to_string())
                ),
                response => panic!("expected IPC error response, got {response:?}"),
            }
        }
    }

    #[test]
    fn sidecar_shutdown_does_not_block_other_window_ipc() {
        let (_app, window) = test_app(Arc::new(Mutex::new(None)), false);

        let shutdown_response =
            dispatch_without_blocking(&window, "shutdown_python", serde_json::json!({}));
        assert!(matches!(
            shutdown_response.try_recv(),
            Err(mpsc::TryRecvError::Empty)
        ));
        test::assert_ipc_response(&window, request("ping", serde_json::json!({})), Ok("pong"));

        match shutdown_response
            .recv_timeout(Duration::from_secs(4))
            .unwrap()
        {
            InvokeResponse::Err(error) => assert_eq!(
                error.0,
                serde_json::Value::String(
                    "Il motore Python non si è arrestato: aggiornamento annullato".to_string()
                )
            ),
            response => panic!("expected IPC error response, got {response:?}"),
        }
    }
}

/// Restituisce le statistiche di utilizzo Groq Cloud
#[tauri::command]
pub async fn get_groq_usage(state: State<'_, AppState>) -> Result<GroqUsage, String> {
    if let Ok(data) = fs::read_to_string(&state.groq_usage_path) {
        if let Ok(usage) = serde_json::from_str::<GroqUsage>(&data) {
            return Ok(usage);
        }
    }
    Ok(GroqUsage::default())
}
