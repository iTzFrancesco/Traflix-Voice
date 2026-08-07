use cpal::traits::{DeviceTrait, HostTrait};
use log::info;
use std::fs;
use tauri::{AppHandle, Emitter, Manager, Runtime, State};

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
    let mut stats = state.stats.lock().unwrap();
    stats.total_words += words;
    stats.total_time += time_delta;

    // total_time is in minutes, so WPM = total_words / total_time_in_minutes
    if stats.total_time > 0.0 {
        stats.avg_wpm = (stats.total_words as f32 / stats.total_time).round() as u32;
    }

    ensure_app_data_dir(&state.stats_path);
    let data = serde_json::to_string_pretty(&*stats).map_err(|e| e.to_string())?;
    atomic_write(&state.stats_path, &data).map_err(|e| e.to_string())?;

    Ok(stats.clone())
}

/// Restituisce le statistiche correnti
#[tauri::command]
pub async fn get_stats(state: State<'_, AppState>) -> Result<AppStats, String> {
    let stats = state.stats.lock().unwrap();
    Ok(stats.clone())
}

/// Restituisce i dispositivi audio disponibili
#[tauri::command]
pub fn get_audio_devices() -> Result<Vec<AudioDeviceInfo>, String> {
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

/// Controlla se un modello esiste già su disco
#[tauri::command]
pub fn check_model_exists(app: AppHandle, model_id: String) -> bool {
    let app_dir = app.path().app_data_dir().unwrap_or_default();
    let model_path = app_dir
        .join("models")
        .join(format!("ggml-{}.bin", model_id));
    model_path.exists()
}

/// Invia un comando al processo Python
#[tauri::command]
pub fn send_to_python(state: State<'_, AppState>, message: String) -> Result<(), String> {
    let mut payload = message.into_bytes();
    payload.push(b'\n');
    write_to_python(state, &payload)
}

/// Fast path for the most latency-sensitive command in the recording flow.
#[tauri::command]
pub fn stop_python(state: State<'_, AppState>) -> Result<(), String> {
    write_to_python(state, b"{\"command\":\"stop\"}\n")
}

fn write_to_python(state: State<'_, AppState>, payload: &[u8]) -> Result<(), String> {
    let mut process_lock = state.python_process.lock().unwrap();
    if let Some(child) = process_lock.as_mut() {
        child.write(payload).map_err(|e| e.to_string())?;
        Ok(())
    } else {
        Err("Motore Python non avviato".to_string())
    }
}

/// Copia il testo negli appunti, simula Ctrl+V, poi ripristina il contenuto precedente
#[tauri::command]
pub async fn execute_paste<R: Runtime>(app: AppHandle<R>, text: String) -> Result<(), String> {
    use std::{thread, time::Duration};
    use tauri_plugin_clipboard_manager::ClipboardExt;

    let previous = app.clipboard().read_text().ok();

    app.clipboard()
        .write_text(text)
        .map_err(|e| e.to_string())?;

    // ClipboardManager::write_text is synchronous; a short settle window is
    // enough before SendInput and avoids adding 30 ms to every paste.
    thread::sleep(Duration::from_millis(20));

    simulate_ctrl_v();

    thread::sleep(Duration::from_millis(100));

    if let Some(prev) = previous {
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
        entries = entries.split_off(entries.len() - 50);
    }

    let data = serde_json::to_string_pretty(&entries).map_err(|e| e.to_string())?;
    atomic_write(&state.history_path, &data).map_err(|e| e.to_string())?;

    Ok(())
}

/// Restituisce la cronologia (ultime 50 trascrizioni, dalla più recente)
#[tauri::command]
pub async fn get_history(state: State<'_, AppState>) -> Result<Vec<TranscriptionEntry>, String> {
    if let Ok(data) = fs::read_to_string(&state.history_path) {
        let mut entries: Vec<TranscriptionEntry> = serde_json::from_str(&data).unwrap_or_default();
        entries.reverse(); // Più recente prima
        Ok(entries)
    } else {
        Ok(Vec::new())
    }
}

/// Cancella tutta la cronologia e resetta le statistiche
#[tauri::command]
pub async fn clear_history(state: State<'_, AppState>) -> Result<(), String> {
    if state.history_path.exists() {
        fs::remove_file(&state.history_path).map_err(|e| e.to_string())?;
    }
    let mut stats = state.stats.lock().unwrap();
    *stats = AppStats::default();
    ensure_app_data_dir(&state.stats_path);
    let data = serde_json::to_string_pretty(&*stats).map_err(|e| e.to_string())?;
    atomic_write(&state.stats_path, &data).map_err(|e| e.to_string())?;
    Ok(())
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
