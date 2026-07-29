use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::sync::atomic::AtomicBool;
use std::sync::{Arc, Mutex, RwLock};
use std::time::Instant;
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
    #[serde(rename = "cloudPostProcessing", default)]
    pub cloud_post_processing: bool,
    #[serde(rename = "removeFillers", default = "default_remove_fillers")]
    pub remove_fillers: bool,
    #[serde(rename = "dictionaryEntries", default)]
    pub dictionary_entries: Vec<DictionaryEntry>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct DictionaryEntry {
    pub id: String,
    pub spoken: String,
    pub replacement: String,
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
fn default_remove_fillers() -> bool {
    true
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
            cloud_post_processing: false,
            remove_fillers: true,
            dictionary_entries: Vec::new(),
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
pub const GROQ_DAILY_LIMIT: f32 = 28_800.0;
#[allow(dead_code)]
pub const GROQ_HOURLY_LIMIT: f32 = 7_200.0;

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

#[derive(Debug, Clone)]
pub struct LastPasteTarget {
    pub paste_id: String,
    pub window_handle: isize,
    pub created_at: Instant,
}

impl LastPasteTarget {
    pub fn can_replace(&self, paste_id: &str, max_age: std::time::Duration) -> bool {
        self.paste_id == paste_id && self.created_at.elapsed() <= max_age
    }
}

// ─── STATO APP ───────────────────────────────────────────────────────────────

pub struct AppState {
    pub stats: Mutex<AppStats>,
    pub python_process: Mutex<Option<CommandChild>>,
    pub settings_path: PathBuf,
    pub stats_path: PathBuf,
    pub history_path: PathBuf,
    #[allow(dead_code)]
    pub models_dir: PathBuf,
    pub groq_usage_path: PathBuf,
    pub last_paste_target: Mutex<Option<LastPasteTarget>>,
    pub hotkey_config: Arc<RwLock<Vec<HotkeyConfig>>>,
    pub is_shutting_down: AtomicBool,
}

#[derive(Debug, Clone)]
pub struct HotkeyConfig {
    pub vk_codes: Vec<i32>,
}

#[cfg(test)]
mod last_paste_tests {
    use super::LastPasteTarget;
    use std::time::{Duration, Instant};

    #[test]
    fn replacement_requires_matching_id_and_fresh_target() {
        let fresh = LastPasteTarget {
            paste_id: "paste-1".to_string(),
            window_handle: 42,
            created_at: Instant::now(),
        };
        assert!(fresh.can_replace("paste-1", Duration::from_secs(60)));
        assert!(!fresh.can_replace("paste-2", Duration::from_secs(60)));

        let expired = LastPasteTarget {
            created_at: Instant::now() - Duration::from_secs(61),
            ..fresh
        };
        assert!(!expired.can_replace("paste-1", Duration::from_secs(60)));
    }
}
