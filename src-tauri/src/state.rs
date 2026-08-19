use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::sync::atomic::AtomicBool;
use std::sync::{Arc, Mutex, RwLock};
use tauri_plugin_shell::process::CommandChild;

// ─── STRUTTURE DATI ──────────────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct AppSettings {
    pub hotkey: String,
    #[serde(rename = "secondaryHotkey", default)]
    pub secondary_hotkey: String,
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
    #[serde(rename = "widgetMode", default = "default_widget_mode")]
    pub widget_mode: String,
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

fn default_widget_mode() -> String {
    "always".to_string()
}

impl Default for AppSettings {
    fn default() -> Self {
        AppSettings {
            hotkey: "XBUTTON2".to_string(),
            secondary_hotkey: String::new(),
            model: "small".to_string(),
            auto_paste: None,
            minimize_tray: true,
            selected_device: "default".to_string(),
            selected_language: "it".to_string(),
            compute_device: "cpu".to_string(),
            hold_to_speak: false,
            groq_api_key: String::new(),
            provider: "local".to_string(),
            widget_mode: "always".to_string(),
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

pub struct AppState {
    pub stats: Mutex<AppStats>,
    pub stats_write_lock: Mutex<()>,
    pub python_process: Mutex<Option<CommandChild>>,
    pub settings_path: PathBuf,
    pub stats_path: PathBuf,
    pub history_path: PathBuf,
    pub history_lock: Mutex<()>,
    pub groq_usage_path: PathBuf,
    pub hotkey_config: Arc<RwLock<Vec<HotkeyConfig>>>,
    pub is_shutting_down: AtomicBool,
}

#[derive(Debug, Clone)]
pub struct HotkeyConfig {
    pub vk_codes: Vec<i32>,
}
