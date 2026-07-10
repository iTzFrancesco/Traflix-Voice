use cpal::traits::{DeviceTrait, HostTrait};
use log::{debug, error, info, warn};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicPtr, Ordering};
use std::sync::{Arc, Mutex};
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    AppHandle, Emitter, Listener, Manager, Runtime, WindowEvent,
};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

#[cfg(windows)]
use windows_sys::Win32::UI::Input::KeyboardAndMouse::GetAsyncKeyState;

// ─── STRUTTURE DATI ──────────────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct AppSettings {
    pub hotkey: String,
    pub model: String,
    #[serde(rename = "autoPaste", default)]
    pub auto_paste: Option<bool>,
    #[serde(rename = "minimizeTray")]
    pub minimize_tray: bool,
    #[serde(rename = "selectedDevice")]
    pub selected_device: String,
    #[serde(rename = "selectedLanguage", default = "default_language")]
    pub selected_language: String,
    #[serde(rename = "computeDevice", default = "default_compute_device")]
    pub compute_device: String,
    #[serde(rename = "holdToSpeak", default = "default_hold_to_speak")]
    pub hold_to_speak: bool,
    #[serde(rename = "groqApiKey", default = "default_empty_string")]
    pub groq_api_key: String,
    #[serde(rename = "provider", default = "default_provider")]
    pub provider: String,
}

fn default_language() -> String {
    "it".to_string()
}

fn default_compute_device() -> String {
    "cpu".to_string()
}

fn default_hold_to_speak() -> bool {
    false
}

fn default_empty_string() -> String {
    String::new()
}

fn default_provider() -> String {
    "local".to_string()
}

impl Default for AppSettings {
    fn default() -> Self {
        AppSettings {
            hotkey: "XBUTTON2".to_string(),
            model: "small".to_string(),
            auto_paste: None,
            minimize_tray: true,
            selected_device: "default".to_string(),
            selected_language: "it".to_string(),
            compute_device: "cpu".to_string(),
            hold_to_speak: false,
            groq_api_key: String::new(),
            provider: "local".to_string(),
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
pub struct GroqUsage {
    pub date: String,
    pub audio_seconds: f32,
    #[serde(rename = "audioSecondsHourly")]
    pub audio_seconds_hourly: f32,
    pub hourly_reset: String,
}

impl Default for GroqUsage {
    fn default() -> Self {
        GroqUsage {
            date: String::new(),
            audio_seconds: 0.0,
            audio_seconds_hourly: 0.0,
            hourly_reset: String::new(),
        }
    }
}

#[allow(dead_code)]
const GROQ_DAILY_LIMIT: f32 = 28_800.0;
#[allow(dead_code)]
const GROQ_HOURLY_LIMIT: f32 = 7_200.0;

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
    groq_usage_path: PathBuf,
    hotkey_config: Arc<AtomicPtr<HotkeyConfig>>,
}

// ─── HELPERS FILE ────────────────────────────────────────────────────────────

fn load_stats_from_file(path: &Path) -> AppStats {
    if let Ok(data) = fs::read_to_string(path) {
        if let Ok(stats) = serde_json::from_str(&data) {
            return stats;
        }
    }
    AppStats::default()
}

#[derive(Debug, Clone)]
struct HotkeyConfig {
    vk_codes: Vec<i32>,
}

fn parse_hotkey(hotkey: &str) -> HotkeyConfig {
    let mut vk_codes = Vec::new();
    for part in hotkey.split('+') {
        if let Some(vk) = str_to_vk(part) {
            vk_codes.push(vk);
        }
    }
    HotkeyConfig { vk_codes }
}

fn str_to_vk(s: &str) -> Option<i32> {
    match s {
        "CommandOrControl" | "Control" | "Ctrl" => Some(0x11), // VK_CONTROL
        "Alt" => Some(0x12),                                   // VK_MENU
        "Shift" => Some(0x10),                                 // VK_SHIFT
        "Super" | "Meta" => Some(0x5B),                        // VK_LWIN
        "Space" => Some(0x20),                                 // VK_SPACE
        "Enter" | "Return" => Some(0x0D),
        "Tab" => Some(0x09),
        "Escape" | "Esc" => Some(0x1B),
        "Backspace" => Some(0x08),
        "Delete" => Some(0x2E),
        "Up" | "ArrowUp" => Some(0x26),
        "Down" | "ArrowDown" => Some(0x28),
        "Left" | "ArrowLeft" => Some(0x25),
        "Right" | "ArrowRight" => Some(0x27),
        "F1" => Some(0x70),
        "F2" => Some(0x71),
        "F3" => Some(0x72),
        "F4" => Some(0x73),
        "F5" => Some(0x74),
        "F6" => Some(0x75),
        "F7" => Some(0x76),
        "F8" => Some(0x77),
        "F9" => Some(0x78),
        "F10" => Some(0x79),
        "F11" => Some(0x7A),
        "F12" => Some(0x7B),
        "A" => Some(0x41),
        "B" => Some(0x42),
        "C" => Some(0x43),
        "D" => Some(0x44),
        "E" => Some(0x45),
        "F" => Some(0x46),
        "G" => Some(0x47),
        "H" => Some(0x48),
        "I" => Some(0x49),
        "J" => Some(0x4A),
        "K" => Some(0x4B),
        "L" => Some(0x4C),
        "M" => Some(0x4D),
        "N" => Some(0x4E),
        "O" => Some(0x4F),
        "P" => Some(0x50),
        "Q" => Some(0x51),
        "R" => Some(0x52),
        "S" => Some(0x53),
        "T" => Some(0x54),
        "U" => Some(0x55),
        "V" => Some(0x56),
        "W" => Some(0x57),
        "X" => Some(0x58),
        "Y" => Some(0x59),
        "Z" => Some(0x5A),
        "0" => Some(0x30),
        "1" => Some(0x31),
        "2" => Some(0x32),
        "3" => Some(0x33),
        "4" => Some(0x34),
        "5" => Some(0x35),
        "6" => Some(0x36),
        "7" => Some(0x37),
        "8" => Some(0x38),
        "9" => Some(0x39),
        // Pulsanti laterali del mouse
        "XBUTTON1" | "XButton1" | "Mouse4" | "Back" => Some(0x05), // VK_XBUTTON1
        "XBUTTON2" | "XButton2" | "Mouse5" | "Forward" => Some(0x06), // VK_XBUTTON2
        "MButton" | "Middle" => Some(0x04),                        // VK_MBUTTON
        _ => None,
    }
}

#[cfg(windows)]
fn is_key_pressed(vk: i32) -> bool {
    unsafe { GetAsyncKeyState(vk) & (0x8000u16 as i16) != 0 }
}

fn load_settings_from_file(path: &Path) -> AppSettings {
    if let Ok(data) = fs::read_to_string(path) {
        if let Ok(settings) = serde_json::from_str(&data) {
            return settings;
        }
    }
    AppSettings::default()
}

fn ensure_app_data_dir(path: &Path) {
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
}

/// Writes data atomically: writes to a `.tmp` file first, then renames to the
/// final path. This prevents corruption if the app crashes mid-write.
fn atomic_write(path: &Path, data: &str) -> std::io::Result<()> {
    let tmp_path = path.with_extension("json.tmp");
    fs::write(&tmp_path, data)?;
    fs::rename(&tmp_path, path)?;
    Ok(())
}

// ─── COMANDI TAURI ───────────────────────────────────────────────────────────

/// Legge e restituisce le impostazioni salvate (o i valori di default)
#[tauri::command]
async fn load_settings(state: tauri::State<'_, AppState>) -> Result<AppSettings, String> {
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
async fn save_settings<R: Runtime>(
    _app: AppHandle<R>,
    state: tauri::State<'_, AppState>,
    settings: AppSettings,
) -> Result<(), String> {
    ensure_app_data_dir(&state.settings_path);
    let data = serde_json::to_string_pretty(&settings).map_err(|e| e.to_string())?;
    info!(
        "[save-debug] save_settings WRITING: hotkey={}, hold_to_speak={}, data_len={}",
        settings.hotkey,
        settings.hold_to_speak,
        data.len()
    );
    atomic_write(&state.settings_path, &data).map_err(|e| e.to_string())?;
    info!("[save-debug] save_settings WRITE OK");

    let new_config = parse_hotkey(&settings.hotkey);
    info!("[Hotkey] Aggiornata a: {:?}", new_config);
    let ptr = Box::into_raw(Box::new(new_config));
    let old = state.hotkey_config.swap(ptr, Ordering::SeqCst);
    if !old.is_null() {
        unsafe {
            drop(Box::from_raw(old));
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
fn check_model_exists(app: AppHandle, model_id: String) -> bool {
    let app_dir = app.path().app_data_dir().unwrap_or_default();
    let model_path = app_dir
        .join("models")
        .join(format!("ggml-{}.bin", model_id));
    model_path.exists()
}

/// Invia un comando al processo Python
#[tauri::command]
async fn send_to_python(state: tauri::State<'_, AppState>, message: String) -> Result<(), String> {
    let mut process_lock = state.python_process.lock().unwrap();
    if let Some(child) = process_lock.as_mut() {
        child
            .write(format!("{}\n", message).as_bytes())
            .map_err(|e| e.to_string())?;
        Ok(())
    } else {
        Err("Motore Python non avviato".to_string())
    }
}

/// Copia il testo negli appunti, simula Ctrl+V, poi ripristina il contenuto precedente
#[tauri::command]
async fn execute_paste<R: Runtime>(app: AppHandle<R>, text: String) -> Result<(), String> {
    use std::{thread, time::Duration};
    use tauri_plugin_clipboard_manager::ClipboardExt;

    let previous = app.clipboard().read_text().ok();

    app.clipboard()
        .write_text(text)
        .map_err(|e| e.to_string())?;

    thread::sleep(Duration::from_millis(50));

    simulate_ctrl_v();

    thread::sleep(Duration::from_millis(100));

    if let Some(prev) = previous {
        let _ = app.clipboard().write_text(prev);
    }

    Ok(())
}

#[cfg(windows)]
fn simulate_ctrl_v() {
    use windows_sys::Win32::UI::Input::KeyboardAndMouse::{
        SendInput, INPUT, INPUT_KEYBOARD, KEYBDINPUT, KEYEVENTF_KEYUP, VK_CONTROL, VK_V,
    };

    let mut inputs: [INPUT; 4] = unsafe { std::mem::zeroed() };

    // Ctrl down
    inputs[0].r#type = INPUT_KEYBOARD;
    inputs[0].Anonymous.ki = KEYBDINPUT {
        wVk: VK_CONTROL,
        wScan: 0,
        dwFlags: 0,
        time: 0,
        dwExtraInfo: 0,
    };

    // V down
    inputs[1].r#type = INPUT_KEYBOARD;
    inputs[1].Anonymous.ki = KEYBDINPUT {
        wVk: VK_V,
        wScan: 0,
        dwFlags: 0,
        time: 0,
        dwExtraInfo: 0,
    };

    // V up
    inputs[2].r#type = INPUT_KEYBOARD;
    inputs[2].Anonymous.ki = KEYBDINPUT {
        wVk: VK_V,
        wScan: 0,
        dwFlags: KEYEVENTF_KEYUP,
        time: 0,
        dwExtraInfo: 0,
    };

    // Ctrl up
    inputs[3].r#type = INPUT_KEYBOARD;
    inputs[3].Anonymous.ki = KEYBDINPUT {
        wVk: VK_CONTROL,
        wScan: 0,
        dwFlags: KEYEVENTF_KEYUP,
        time: 0,
        dwExtraInfo: 0,
    };

    unsafe {
        SendInput(4, inputs.as_ptr(), std::mem::size_of::<INPUT>() as i32);
    }
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

/// Restituisce le statistiche di utilizzo Groq Cloud
#[tauri::command]
async fn get_groq_usage(state: tauri::State<'_, AppState>) -> Result<GroqUsage, String> {
    if let Ok(data) = fs::read_to_string(&state.groq_usage_path) {
        if let Ok(usage) = serde_json::from_str::<GroqUsage>(&data) {
            return Ok(usage);
        }
    }
    Ok(GroqUsage::default())
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
            let groq_usage_path = app_data_dir.join("groq_usage.json");
            let models_dir      = app_data_dir.join("models");
            let _ = fs::create_dir_all(&models_dir);

            let settings = load_settings_from_file(&settings_path);
            let initial_config = parse_hotkey(&settings.hotkey);
            info!("[Hotkey] Configurata: {:?}", initial_config);
            let hotkey_config = Arc::new(AtomicPtr::new(Box::into_raw(Box::new(initial_config))));

            app.manage(AppState {
                stats:           Mutex::new(load_stats_from_file(&stats_path)),
                python_process:  Mutex::new(None),
                settings_path,
                stats_path,
                history_path,
                models_dir:       models_dir.clone(),
                groq_usage_path:  groq_usage_path.clone(),
                hotkey_config:    hotkey_config.clone(),
            });

            // Hotkey polling via GetAsyncKeyState (~60Hz, no hooks, no message pump)
            let app_handle_kb = app.handle().clone();
            std::thread::spawn(move || {
                let mut hotkey_active = false;

                loop {
                    std::thread::sleep(std::time::Duration::from_millis(16));

                    let config_ptr = hotkey_config.load(Ordering::SeqCst);
                    if config_ptr.is_null() { continue; }
                    let config = unsafe { &*config_ptr };

                    if config.vk_codes.is_empty() { continue; }

                    let all_pressed = config.vk_codes.iter().all(|&vk| is_key_pressed(vk));

                    if all_pressed && !hotkey_active {
                        hotkey_active = true;
                        debug!("[Hotkey] Pressed");
                        let _ = app_handle_kb.emit("hotkey_pressed", ());
                    } else if !all_pressed && hotkey_active {
                        hotkey_active = false;
                        debug!("[Hotkey] Released");
                        let _ = app_handle_kb.emit("hotkey_released", ());
                    }
                }
            });

            // Avvio Python sidecar (con health-check e auto-restart)
            let app_handle = app.handle().clone();
            let models_dir_str = models_dir.to_string_lossy().to_string();
            let resource_dir = app.path().resource_dir().expect("Impossibile trovare resource dir");
            let script_path = resource_dir.join("whisper_engine.py");
            let script_path_str = script_path.to_string_lossy().to_string();
            info!("[Python sidecar] Script path: {}", script_path_str);

            std::thread::spawn(move || {
                let mut restart_count: u32 = 0;
                const MAX_BACKOFF_SECS: u64 = 10;

                loop {
                    info!("[Python sidecar] Spawning python process (attempt #{})", restart_count + 1);

                    let shell = app_handle.shell();
                    let spawn_result = shell
                        .command("python")
                        .args([&script_path_str])
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
                    let (selected_model, compute_device, groq_api_key, provider) = {
                        let s = load_settings_from_file(&app_handle.state::<AppState>().settings_path);
                        (s.model, s.compute_device, s.groq_api_key, s.provider)
                    };
                    let _ = child.write(format!(
                        "{{\"command\": \"init\", \"models_dir\": \"{}\", \"compute_device\": \"{}\", \"model\": \"{}\", \"groq_api_key\": \"{}\", \"provider\": \"{}\"}}\n",
                        models_dir_str.replace("\\", "\\\\"),
                        compute_device,
                        selected_model,
                        groq_api_key,
                        provider,
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
                        // Send quit command to Python for clean model unload
                        if let Some(child) = handle.state::<AppState>().python_process.lock().unwrap().as_mut() {
                            let _ = child.write(b"{\"command\": \"quit\"}\n");
                        }
                        std::thread::sleep(std::time::Duration::from_millis(200));
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
            get_groq_usage,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

// ─── TEST ─────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_str_to_vk() {
        assert_eq!(str_to_vk("Control"), Some(0x11));
        assert_eq!(str_to_vk("Alt"), Some(0x12));
        assert_eq!(str_to_vk("Space"), Some(0x20));
        assert_eq!(str_to_vk("A"), Some(0x41));
        assert_eq!(str_to_vk("XBUTTON2"), Some(0x06));
        assert_eq!(str_to_vk("F1"), Some(0x70));
        assert_eq!(str_to_vk("Nonexistent"), None);
    }

    #[test]
    fn test_parse_hotkey() {
        let cfg = parse_hotkey("CommandOrControl+Space");
        assert_eq!(cfg.vk_codes, vec![0x11, 0x20]);

        let cfg = parse_hotkey("Control+Shift+A");
        assert_eq!(cfg.vk_codes, vec![0x11, 0x10, 0x41]);

        let cfg = parse_hotkey("XBUTTON2");
        assert_eq!(cfg.vk_codes, vec![0x06]);
    }

    #[test]
    fn test_app_settings_default() {
        let s = AppSettings::default();
        assert_eq!(s.hotkey, "XBUTTON2");
        assert!(!s.hold_to_speak);
        assert_eq!(s.model, "small");
        assert_eq!(s.selected_language, "it");
    }

    #[test]
    fn test_settings_json_roundtrip() {
        let dir = std::env::temp_dir().join("traflix_test_settings");
        let _ = std::fs::create_dir_all(&dir);
        let path = dir.join("settings.json");

        // Write test settings
        let original = AppSettings {
            hotkey: "XBUTTON2".to_string(),
            model: "small".to_string(),
            auto_paste: None,
            minimize_tray: true,
            selected_device: "default".to_string(),
            selected_language: "it".to_string(),
            compute_device: "cpu".to_string(),
            hold_to_speak: false,
            groq_api_key: String::new(),
            provider: "local".to_string(),
        };

        let json = serde_json::to_string_pretty(&original).unwrap();
        atomic_write(&path, &json).unwrap();

        // Verify file exists and has content
        assert!(path.exists());
        let content = std::fs::read_to_string(&path).unwrap();
        assert!(content.contains("XBUTTON2"));

        // Load and verify
        let loaded = load_settings_from_file(&path);
        assert_eq!(loaded.hotkey, original.hotkey);
        assert_eq!(loaded.model, original.model);
        assert_eq!(loaded.minimize_tray, original.minimize_tray);
        assert_eq!(loaded.selected_device, original.selected_device);
        assert_eq!(loaded.selected_language, original.selected_language);
        assert_eq!(loaded.compute_device, original.compute_device);
        assert!(!loaded.hold_to_speak);

        // Modify and save again
        let modified = AppSettings {
            hotkey: "Control+Shift+A".to_string(),
            ..original
        };
        let json2 = serde_json::to_string_pretty(&modified).unwrap();
        atomic_write(&path, &json2).unwrap();

        let reloaded = load_settings_from_file(&path);
        assert_eq!(reloaded.hotkey, "Control+Shift+A");
        assert_eq!(reloaded.model, "small"); // unchanged

        // Cleanup
        let _ = std::fs::remove_file(&path);
        let _ = std::fs::remove_dir(&dir);
    }

    #[test]
    fn test_atomic_write_no_corruption() {
        let dir = std::env::temp_dir().join("traflix_test_atomic");
        let _ = std::fs::create_dir_all(&dir);
        let path = dir.join("test.json");

        // Write initial
        atomic_write(&path, r#"{"test": "initial"}"#).unwrap();
        assert_eq!(
            std::fs::read_to_string(&path).unwrap(),
            r#"{"test": "initial"}"#
        );

        // No .tmp file should remain
        assert!(!path.with_extension("json.tmp").exists());

        // Overwrite
        atomic_write(&path, r#"{"test": "overwritten"}"#).unwrap();
        assert_eq!(
            std::fs::read_to_string(&path).unwrap(),
            r#"{"test": "overwritten"}"#
        );

        // Cleanup
        let _ = std::fs::remove_file(&path);
        let _ = std::fs::remove_dir(&dir);
    }

    #[test]
    fn test_load_settings_nonexistent_file() {
        let dir = std::env::temp_dir().join("traflix_test_nonexistent");
        let _ = std::fs::create_dir_all(&dir);
        let path = dir.join("nonexistent.json");

        // Should return defaults
        let settings = load_settings_from_file(&path);
        assert_eq!(settings.hotkey, "XBUTTON2");
        assert_eq!(settings.model, "small");
        assert!(!settings.hold_to_speak);

        let _ = std::fs::remove_dir(&dir);
    }

    #[test]
    fn test_load_settings_corrupted_file() {
        let dir = std::env::temp_dir().join("traflix_test_corrupted");
        let _ = std::fs::create_dir_all(&dir);
        let path = dir.join("corrupted.json");

        // Write invalid JSON
        std::fs::write(&path, r#"{invalid json here"#).unwrap();

        // Should return defaults
        let settings = load_settings_from_file(&path);
        assert_eq!(settings.hotkey, "XBUTTON2");

        let _ = std::fs::remove_file(&path);
        let _ = std::fs::remove_dir(&dir);
    }

    #[test]
    fn test_settings_serde_field_mapping() {
        // Test that serde rename attributes work correctly
        let json = r#"{
            "hotkey": "Control+Space",
            "model": "medium",
            "autoPaste": null,
            "minimizeTray": false,
            "selectedDevice": "Microphone (Realtek)",
            "selectedLanguage": "en",
            "computeDevice": "cuda",
            "holdToSpeak": true
        }"#;

        let settings: AppSettings = serde_json::from_str(json).unwrap();
        assert_eq!(settings.hotkey, "Control+Space");
        assert_eq!(settings.model, "medium");
        assert_eq!(settings.auto_paste, None);
        assert!(!settings.minimize_tray);
        assert_eq!(settings.selected_device, "Microphone (Realtek)");
        assert_eq!(settings.selected_language, "en");
        assert_eq!(settings.compute_device, "cuda");
        assert!(settings.hold_to_speak);

        // Round-trip back to JSON
        let serialized = serde_json::to_string(&settings).unwrap();
        assert!(serialized.contains("\"minimizeTray\""));
        assert!(serialized.contains("\"selectedDevice\""));
        assert!(serialized.contains("\"selectedLanguage\""));
        assert!(serialized.contains("\"computeDevice\""));
        assert!(serialized.contains("\"holdToSpeak\""));
        assert!(serialized.contains("\"autoPaste\""));
    }

    #[test]
    fn test_hotkey_config_sync_atomic_ptr() {
        // Simulate what happens in the app: create, swap, and verify
        let ptr = Arc::new(AtomicPtr::new(Box::into_raw(Box::new(parse_hotkey(
            "XBUTTON2",
        )))));

        // Verify initial value
        let config_ptr = ptr.load(Ordering::SeqCst);
        assert!(!config_ptr.is_null());
        let config = unsafe { &*config_ptr };
        assert_eq!(config.vk_codes, vec![0x06]);

        // Swap to new value
        let new_config = Box::into_raw(Box::new(parse_hotkey("Control+Alt+Space")));
        let old = ptr.swap(new_config, Ordering::SeqCst);
        if !old.is_null() {
            unsafe {
                drop(Box::from_raw(old));
            }
        }

        // Verify new value
        let config_ptr = ptr.load(Ordering::SeqCst);
        let config = unsafe { &*config_ptr };
        assert_eq!(config.vk_codes, vec![0x11, 0x12, 0x20]);

        // Cleanup
        let last = ptr.load(Ordering::SeqCst);
        if !last.is_null() {
            unsafe {
                drop(Box::from_raw(last));
            }
        }
    }
}
