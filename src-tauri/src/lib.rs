use log::{debug, error, info, warn};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
use std::sync::Mutex;
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    AppHandle, Emitter, Listener, Manager, Runtime, WindowEvent,
};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutEvent, ShortcutState};
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandChild;
use std::str::FromStr;
use cpal::traits::{DeviceTrait, HostTrait};
use rdev::{listen, Event, EventType, Key};

// ─── STRUTTURE DATI ──────────────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct AppSettings {
    pub hotkey: String,
    pub model: String,
    #[serde(rename = "autoPaste")]
    pub auto_paste: bool,
    #[serde(rename = "minimizeTray")]
    pub minimize_tray: bool,
    #[serde(rename = "selectedDevice")]
    pub selected_device: String,
    #[serde(rename = "selectedLanguage", default = "default_language")]
    pub selected_language: String,
    #[serde(rename = "computeDevice", default = "default_compute_device")]
    pub compute_device: String,
}

fn default_language() -> String {
    "it".to_string()
}

fn default_compute_device() -> String {
    "cpu".to_string()
}

impl Default for AppSettings {
    fn default() -> Self {
        AppSettings {
            hotkey: "CommandOrControl+Space".to_string(),
            model: "small".to_string(),
            auto_paste: true,
            minimize_tray: true,
            selected_device: "default".to_string(),
            selected_language: "it".to_string(),
            compute_device: "cpu".to_string(),
        }
    }
}

#[derive(Debug, Serialize, Deserialize, Clone, Default)]
pub struct AppStats {
    pub total_words: u32,
    pub avg_wpm: u32,
    pub total_time: f32,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct TranscriptionEntry {
    pub text: String,
    pub timestamp: String,
    pub word_count: u32,
}

#[derive(Serialize)]
pub struct AudioDeviceInfo {
    pub id: String,
    pub name: String,
}

// ─── STATO APP ───────────────────────────────────────────────────────────────

struct AppState {
    stats: Mutex<AppStats>,
    python_process: Mutex<Option<CommandChild>>,
    settings_path: PathBuf,
    stats_path: PathBuf,
    history_path: PathBuf,
    #[allow(dead_code)]
    models_dir: PathBuf,
}

// ─── HELPERS FILE ────────────────────────────────────────────────────────────

fn load_stats_from_file(path: &PathBuf) -> AppStats {
    if let Ok(data) = fs::read_to_string(path) {
        if let Ok(stats) = serde_json::from_str(&data) {
            return stats;
        }
    }
    AppStats::default()
}

fn load_settings_from_file(path: &PathBuf) -> AppSettings {
    if let Ok(data) = fs::read_to_string(path) {
        if let Ok(settings) = serde_json::from_str(&data) {
            return settings;
        }
    }
    AppSettings::default()
}

fn ensure_app_data_dir(path: &PathBuf) {
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
}

/// Writes data atomically: writes to a `.tmp` file first, then renames to the
/// final path. This prevents corruption if the app crashes mid-write.
fn atomic_write(path: &PathBuf, data: &str) -> std::io::Result<()> {
    let tmp_path = path.with_extension("json.tmp");
    fs::write(&tmp_path, data)?;
    fs::rename(&tmp_path, path)?;
    Ok(())
}

// ─── COMANDI TAURI ───────────────────────────────────────────────────────────

/// Legge e restituisce le impostazioni salvate (o i valori di default)
#[tauri::command]
async fn load_settings(state: tauri::State<'_, AppState>) -> Result<AppSettings, String> {
    Ok(load_settings_from_file(&state.settings_path))
}

/// Salva le impostazioni su disco E le applica (hotkey globale)
#[tauri::command]
async fn save_settings<R: Runtime>(
    app: AppHandle<R>,
    state: tauri::State<'_, AppState>,
    settings: AppSettings,
) -> Result<(), String> {
    // Persisti su disco
    ensure_app_data_dir(&state.settings_path);
    let data = serde_json::to_string_pretty(&settings).map_err(|e| e.to_string())?;
    atomic_write(&state.settings_path, &data).map_err(|e| e.to_string())?;

    // Applica hotkey globale (Solo se non è una scorciatoia speciale gestita dall'hook)
    let manager = app.global_shortcut();
    let _ = manager.unregister_all();
    
    let is_special = settings.hotkey.contains("Alt") && settings.hotkey.contains("Control") && !settings.hotkey.contains("+") || 
                     settings.hotkey == "CommandOrControl+Alt" || 
                     settings.hotkey == "Control+Alt";

    if !is_special {
        if let Ok(shortcut) = Shortcut::from_str(&settings.hotkey) {
            let _ = manager.on_shortcut(shortcut, move |handle, _shortcut, event: ShortcutEvent| {
                if event.state() == ShortcutState::Pressed {
                    let _ = handle.emit("hotkey_pressed", ());
                } else if event.state() == ShortcutState::Released {
                    let _ = handle.emit("hotkey_released", ());
                }
            });
        }
    }

    Ok(())
}

/// Aggiorna le statistiche e le salva su disco
#[tauri::command]
async fn update_stats(
    state: tauri::State<'_, AppState>,
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
async fn get_stats(state: tauri::State<'_, AppState>) -> Result<AppStats, String> {
    let stats = state.stats.lock().unwrap();
    Ok(stats.clone())
}

/// Restituisce i dispositivi audio disponibili
#[tauri::command]
fn get_audio_devices() -> Result<Vec<AudioDeviceInfo>, String> {
    let host = cpal::default_host();
    let mut devices = Vec::new();
    let input_devices = host.input_devices().map_err(|e| e.to_string())?;
    for device in input_devices {
        if let Ok(name) = device.name() {
            devices.push(AudioDeviceInfo { id: name.clone(), name });
        }
    }
    Ok(devices)
}

/// Controlla se un modello esiste già su disco
#[tauri::command]
fn check_model_exists(app: AppHandle, model_id: String) -> bool {
    let app_dir = app.path().app_data_dir().unwrap_or_default();
    let model_path = app_dir.join("models").join(format!("faster-whisper-{}", model_id));
    model_path.join("model.bin").exists()
}

/// Invia un comando al processo Python
#[tauri::command]
async fn send_to_python(state: tauri::State<'_, AppState>, message: String) -> Result<(), String> {
    let mut process_lock = state.python_process.lock().unwrap();
    if let Some(child) = process_lock.as_mut() {
        child.write(format!("{}\n", message).as_bytes()).map_err(|e| e.to_string())?;
        Ok(())
    } else {
        Err("Motore Python non avviato".to_string())
    }
}

/// Copia il testo negli appunti e simula Ctrl+V
#[tauri::command]
async fn execute_paste<R: Runtime>(app: AppHandle<R>, text: String) -> Result<(), String> {
    use tauri_plugin_clipboard_manager::ClipboardExt;
    use rdev::{simulate, EventType, Key};
    use std::{thread, time::Duration};

    // 1. Scrivi negli appunti
    app.clipboard().write_text(text).map_err(|e| e.to_string())?;

    // 2. 50ms delay: gives the OS clipboard manager enough time to commit the
    //    new content before the simulated Ctrl+V keystroke reads it. Shorter
    //    values (~10-20ms) cause sporadic stale-paste on Windows; 50ms is the
    //    minimum reliable across Win10/11 and most clipboard-hooking tools.
    thread::sleep(Duration::from_millis(50));

    // 3. Simula CTRL + V (Windows/Linux) o CMD + V (Mac)
    #[cfg(target_os = "macos")]
    let modifier = Key::MetaLeft;
    #[cfg(not(target_os = "macos"))]
    let modifier = Key::ControlLeft;

    let _ = simulate(&EventType::KeyPress(modifier));
    let _ = simulate(&EventType::KeyPress(Key::KeyV));
    let _ = simulate(&EventType::KeyRelease(Key::KeyV));
    let _ = simulate(&EventType::KeyRelease(modifier));

    Ok(())
}

// ─── COMANDI CRONOLOGIA ──────────────────────────────────────────────────────

/// Salva una trascrizione nella cronologia (history.json)
#[tauri::command]
async fn save_transcription(
    state: tauri::State<'_, AppState>,
    text: String,
    timestamp: String,
    word_count: u32,
) -> Result<(), String> {
    ensure_app_data_dir(&state.history_path);

    let mut entries: Vec<TranscriptionEntry> = if let Ok(data) = fs::read_to_string(&state.history_path) {
        serde_json::from_str(&data).unwrap_or_default()
    } else {
        Vec::new()
    };

    entries.push(TranscriptionEntry { text, timestamp, word_count });

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
async fn get_history(state: tauri::State<'_, AppState>) -> Result<Vec<TranscriptionEntry>, String> {
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
async fn clear_history(state: tauri::State<'_, AppState>) -> Result<(), String> {
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

// ─── ENTRY POINT ─────────────────────────────────────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let app_data_dir    = app.path().app_data_dir().expect("Impossibile trovare directory dati");
            let stats_path      = app_data_dir.join("stats.json");
            let settings_path   = app_data_dir.join("settings.json");
            let history_path    = app_data_dir.join("history.json");
            let models_dir      = app_data_dir.join("models");
            let _ = fs::create_dir_all(&models_dir);

            let settings = load_settings_from_file(&settings_path);

            app.manage(AppState {
                stats:          Mutex::new(load_stats_from_file(&stats_path)),
                python_process: Mutex::new(None),
                settings_path,
                stats_path,
                history_path,
                models_dir: models_dir.clone(),
            });

            // Registra hotkey all'avvio
            let manager = app.global_shortcut();
            let is_special = settings.hotkey == "CommandOrControl+Alt" || settings.hotkey == "Control+Alt";
            
            if !is_special {
                if let Ok(shortcut) = Shortcut::from_str(&settings.hotkey) {
                    let _ = manager.on_shortcut(shortcut, |handle, _shortcut, event| {
                        if event.state() == ShortcutState::Pressed {
                            let _ = handle.emit("hotkey_pressed", ());
                        } else if event.state() == ShortcutState::Released {
                            let _ = handle.emit("hotkey_released", ());
                        }
                    });
                }
            }

            // Avvio Keyboard Listener per scorciatoie speciali (es. Control+Alt)
            let app_handle_kb = app.handle().clone();
            std::thread::spawn(move || {
                let mut ctrl_pressed = false;
                let mut alt_pressed = false;
                let mut both_active = false;

                if let Err(error) = listen(move |event: Event| {
                    match event.event_type {
                        EventType::KeyPress(key) => {
                            if key == Key::ControlLeft || key == Key::ControlRight { ctrl_pressed = true; }
                            if key == Key::Alt || key == Key::AltGr { alt_pressed = true; }
                        }
                        EventType::KeyRelease(key) => {
                            if key == Key::ControlLeft || key == Key::ControlRight { ctrl_pressed = false; }
                            if key == Key::Alt || key == Key::AltGr { alt_pressed = false; }
                        }
                        _ => {}
                    }

                    // Logica di trigger
                    if ctrl_pressed && alt_pressed {
                        if !both_active {
                            both_active = true;
                            debug!("[Hook] Triggered: Control + Alt");
                            let _ = app_handle_kb.emit("hotkey_pressed", ());
                        }
                    } else {
                        if both_active {
                            both_active = false;
                            debug!("[Hook] Released: Control + Alt");
                            let _ = app_handle_kb.emit("hotkey_released", ());
                        }
                    }
                }) {
                    error!("[Hook] Critical error: {:?}", error);
                }
            });

            // Avvio Python sidecar (con health-check e auto-restart)
            let app_handle = app.handle().clone();
            let models_dir_str = models_dir.to_string_lossy().to_string();
            std::thread::spawn(move || {
                let mut restart_count: u32 = 0;
                // Back-off delays: 1s, 2s, 4s, 8s, then cap at 10s
                const MAX_BACKOFF_SECS: u64 = 10;

                loop {
                    info!("[Python sidecar] Spawning python process (attempt #{})", restart_count + 1);

                    let shell = app_handle.shell();
                    let spawn_result = shell
                        .command("python")
                        .args(["whisper_engine.py"])
                        .spawn();

                    let (mut rx, mut child) = match spawn_result {
                        Ok(pair) => pair,
                        Err(e) => {
                            error!("[Python sidecar] Failed to spawn: {:?}", e);
                            let delay = std::cmp::min(2u64.saturating_pow(restart_count), MAX_BACKOFF_SECS);
                            std::thread::sleep(std::time::Duration::from_secs(delay));
                            restart_count += 1;
                            continue;
                        }
                    };

                    // Send init command (models_dir + compute_device)
                    let compute_device = {
                        let s = load_settings_from_file(&app_handle.state::<AppState>().settings_path);
                        s.compute_device
                    };
                    let _ = child.write(format!(
                        "{{\"command\": \"init\", \"models_dir\": \"{}\", \"compute_device\": \"{}\"}}\n",
                        models_dir_str.replace("\\", "\\\\"),
                        compute_device
                    ).as_bytes());

                    // Store the child handle so send_to_python can write to it
                    *app_handle.state::<AppState>().python_process.lock().unwrap() = Some(child);

                    if restart_count > 0 {
                        warn!("[Python sidecar] Process restarted (restart #{})", restart_count);
                        let _ = app_handle.emit("python_restarted", restart_count);
                    }

                    // Read stdout until the process exits (rx channel closes)
                    while let Some(event) = rx.blocking_recv() {
                        if let tauri_plugin_shell::process::CommandEvent::Stdout(line) = event {
                            let _ = app_handle.emit("python_output", String::from_utf8_lossy(&line).to_string());
                        }
                    }

                    // If we reach here, the Python process has died
                    error!("[Python sidecar] Process exited unexpectedly, will restart");

                    // Clear the stale child handle
                    *app_handle.state::<AppState>().python_process.lock().unwrap() = None;

                    // Back-off before restarting
                    restart_count += 1;
                    let delay = std::cmp::min(2u64.saturating_pow(restart_count), MAX_BACKOFF_SECS);
                    info!("[Python sidecar] Waiting {}s before restart...", delay);
                    std::thread::sleep(std::time::Duration::from_secs(delay));
                }
            });

            // Tray Menu
            let show_i = MenuItem::with_id(app, "show", "Mostra", true, None::<&str>)?;
            let quit_i = MenuItem::with_id(app, "quit", "Esci",   true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show_i, &quit_i])?;

            let _tray = TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .menu(&menu)
                .on_menu_event(|handle, event| {
                    if event.id.as_ref() == "show" {
                        if let Some(main_win) = handle.get_webview_window("main") {
                            let _ = main_win.show();
                            let _ = main_win.set_focus();
                        }
                        if let Some(overlay) = handle.get_webview_window("overlay") {
                            let _ = overlay.hide();
                        }
                    } else if event.id.as_ref() == "quit" {
                        handle.exit(0);
                    }
                })
                .build(app)?;

            // Listen for show_main_window event from overlay
            let app_handle_show = app.handle().clone();
            app.listen("show_main_window", move |_| {
                if let Some(main_win) = app_handle_show.get_webview_window("main") {
                    let _ = main_win.show();
                    let _ = main_win.set_focus();
                }
                if let Some(overlay) = app_handle_show.get_webview_window("overlay") {
                    let _ = overlay.hide();
                }
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == "main" {
                    api.prevent_close();
                    let _ = window.hide();
                    // Show the mini overlay widget
                    if let Some(overlay) = window.app_handle().get_webview_window("overlay") {
                        let _ = overlay.show();
                        let _ = overlay.set_focus();
                    }
                } else if window.label() == "overlay" {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .plugin(tauri_plugin_log::Builder::new().build())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            load_settings,
            save_settings,
            get_stats,
            update_stats,
            get_audio_devices,
            send_to_python,
            check_model_exists,
            execute_paste,
            save_transcription,
            get_history,
            clear_history,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
