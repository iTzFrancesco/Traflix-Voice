mod commands;
mod hotkey;
#[cfg(desktop)]
mod hotkey_runtime;
#[cfg(desktop)]
mod mouse_suppress;
mod settings;
#[cfg(desktop)]
mod sidecar;
mod state;
#[cfg(desktop)]
mod window_runtime;

mod clipboard;
#[cfg(target_os = "android")]
mod mobile_runtime;

// Re-exports for compatibility — tests use `use super::*` and run() needs direct access
pub use commands::*;
pub use hotkey::is_key_pressed;
pub use hotkey::{parse_hotkey, str_to_vk};
pub use settings::*;
pub use state::*;

#[cfg(desktop)]
use log::info;
use std::fs;
use std::sync::atomic::AtomicBool;
#[cfg(test)]
use std::sync::atomic::Ordering;
use std::sync::{Arc, Mutex, RwLock};
#[cfg(desktop)]
use tauri::Emitter;
use tauri::Manager;

// ─── ENTRY POINT ─────────────────────────────────────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // reqwest 0.13 disables implicit rustls provider selection. Install the
    // ring provider before any updater/client code can construct a TLS client.
    let _ = rustls::crypto::ring::default_provider().install_default();

    let builder = tauri::Builder::default().setup(|app| {
        let app_data_dir = app
            .path()
            .app_data_dir()
            .expect("Impossibile trovare directory dati");
        let stats_path = app_data_dir.join("stats.json");
        let settings_path = app_data_dir.join("settings.json");
        let history_path = app_data_dir.join("history.json");
        let groq_usage_path = app_data_dir.join("groq_usage.json");
        let models_dir = app_data_dir.join("models");
        let _ = fs::create_dir_all(&models_dir);

        let hotkey_config = Arc::new(RwLock::new(Vec::new()));

        let settings = load_settings_from_file(&settings_path);
        let keep_clipboard_result = AtomicBool::new(settings.keep_clipboard_result);

        #[cfg(desktop)]
        {
            let initial_config = [settings.hotkey.as_str(), settings.secondary_hotkey.as_str()]
                .into_iter()
                .filter(|hotkey| !hotkey.trim().is_empty())
                .map(parse_hotkey)
                .filter(|config| !config.vk_codes.is_empty())
                .collect::<Vec<_>>();
            info!("[Hotkey] Configurate: {:?}", initial_config);
            *hotkey_config.write().unwrap() = initial_config;
        }

        app.manage(AppState {
            stats: Mutex::new(load_stats_from_file(&stats_path)),
            stats_write_lock: Mutex::new(()),
            python_process: Mutex::new(None),
            settings_path: settings_path.clone(),
            stats_path,
            history_path,
            history_lock: Mutex::new(()),
            groq_usage_path: groq_usage_path.clone(),
            hotkey_config: hotkey_config.clone(),
            keep_clipboard_result,
            is_shutting_down: AtomicBool::new(false),
            python_process_exited: AtomicBool::new(true),
        });

        #[cfg(desktop)]
        {
            let app_handle = app.handle().clone();
            hotkey_runtime::spawn(app_handle.clone(), hotkey_config);
            // Ingoia XBUTTON/MButton configurati come hotkey così non navigano
            // nel browser mentre Traflix registra (alla chiusura tutto torna
            // normale perché l'hook muore col processo).
            mouse_suppress::spawn();

            #[cfg(debug_assertions)]
            let sidecar_path =
                std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("whisper_engine.py");
            #[cfg(not(debug_assertions))]
            let sidecar_path = {
                let resource_dir = app
                    .path()
                    .resource_dir()
                    .expect("Impossibile trovare resource dir");
                let packaged_backend = resource_dir
                    .join("python-backend")
                    .join("whisper_engine")
                    .join("whisper_engine.exe");
                if packaged_backend.is_file() {
                    packaged_backend
                } else {
                    resource_dir.join("whisper_engine.py")
                }
            };
            sidecar::spawn(app_handle.clone(), sidecar_path, models_dir.clone());

            let settings = load_settings_from_file(&settings_path);
            let _ = app.emit("widget_mode_updated", settings.widget_mode.clone());
            window_runtime::setup_tray(app)?;
            window_runtime::install_listeners(app);
        }

        Ok(())
    });
    // These plugins own desktop-only integrations (sidecar, clipboard paste,
    // tray diagnostics, and the desktop updater). Keeping them out of the
    // Android builder avoids loading unsupported platform adapters during
    // application startup.
    #[cfg(desktop)]
    let builder = builder
        .plugin(tauri_plugin_log::Builder::new().build())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_opener::init());

    #[cfg(target_os = "android")]
    let builder = builder
        .plugin(mobile_runtime::init())
        .plugin(mobile_runtime::updater_init());

    #[cfg(desktop)]
    let builder = builder.on_window_event(window_runtime::handle_window_event);

    #[cfg(all(not(debug_assertions), desktop))]
    let builder = builder.plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
        window_runtime::show_main_window(app);
    }));

    builder
        .invoke_handler(tauri::generate_handler![
            is_dev,
            load_settings,
            save_settings,
            set_hotkey_capture_active,
            get_stats,
            update_stats,
            get_audio_devices,
            send_to_python,
            stop_python,
            check_model_exists,
            execute_paste,
            save_transcription,
            get_history,
            delete_history_entry,
            clear_history,
            get_groq_usage,
            shutdown_python,
            restart_app,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

// ─── TEST ─────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    #[test]
    fn cloud_usage_reads_sidecar_audio_and_correction_counters() {
        let usage: crate::state::GroqUsage = serde_json::from_value(serde_json::json!({
            "date": "2026-10-02", "audio_seconds": 15.6,
            "audio_seconds_hourly": 10.2, "hourly_reset": "15:00",
            "_hour_bucket": 497000, "llmInputTokens": 226,
            "llmOutputTokens": 86, "llmInputTokensHourly": 200,
            "llmOutputTokensHourly": 80
        }))
        .unwrap();
        assert_eq!(usage.audio_seconds_hourly, 10.2);
        assert_eq!(usage.hour_key, 497000);
        assert_eq!(usage.llm_input_tokens, 226);
        assert_eq!(usage.llm_output_tokens_hourly, 80);
        let encoded = serde_json::to_value(usage).unwrap();
        assert_eq!(encoded["audioSecondsHourly"], serde_json::json!(10.2_f32));
        assert_eq!(encoded["llmOutputTokens"], 86);
    }

    use super::*;

    #[test]
    fn test_str_to_vk() {
        assert_eq!(str_to_vk("Control"), Some(0x11));
        assert_eq!(str_to_vk("ControlLeft"), Some(0xA2));
        assert_eq!(str_to_vk("ControlRight"), Some(0xA3));
        assert_eq!(str_to_vk("Alt"), Some(0x12));
        assert_eq!(str_to_vk("AltGraph"), Some(0xA5));
        assert_eq!(str_to_vk("Space"), Some(0x20));
        assert_eq!(str_to_vk("A"), Some(0x41));
        assert_eq!(str_to_vk("XBUTTON2"), Some(0x06));
        assert_eq!(str_to_vk("F1"), Some(0x70));
        assert_eq!(str_to_vk("Ù"), Some(0xE2));
        assert_eq!(str_to_vk("Nonexistent"), None);
    }

    #[test]
    fn test_parse_hotkey() {
        let cfg = parse_hotkey("CommandOrControl+Space");
        assert_eq!(cfg.vk_codes, vec![0x11, 0x20]);

        let cfg = parse_hotkey("Control+Shift+A");
        assert_eq!(cfg.vk_codes, vec![0x11, 0x10, 0x41]);

        let cfg = parse_hotkey("ControlRight");
        assert_eq!(cfg.vk_codes, vec![0xA3]);

        let cfg = parse_hotkey("XBUTTON2");
        assert_eq!(cfg.vk_codes, vec![0x06]);
    }

    #[test]
    fn test_app_settings_default() {
        let s = AppSettings::default();
        assert_eq!(s.hotkey, "XBUTTON2");
        assert!(!s.hold_to_speak);
        assert_eq!(s.model, "parakeet-tdt-0.6b-v3-int8");
        assert_eq!(s.selected_language, "it");
        assert!(s.keep_clipboard_result);
        assert!(s.cloud_correction_enabled);
        assert!(s.cloud_vocabulary.is_empty());
        assert!(s.cloud_speech_filter);
    }

    #[test]
    fn test_keep_clipboard_result_defaults_to_true() {
        // A settings.json written by an older build must keep the transcript in
        // the clipboard, otherwise the user loses it with no recovery path.
        let legacy = r#"{
            "hotkey": "XBUTTON2",
            "model": "parakeet-tdt-0.6b-v3-int8",
            "minimizeTray": true,
            "selectedDevice": "default",
            "selectedLanguage": "it",
            "computeDevice": "cpu",
            "holdToSpeak": false,
            "groqApiKey": "",
            "provider": "local"
        }"#;
        let settings: AppSettings = serde_json::from_str(legacy).unwrap();
        assert!(settings.keep_clipboard_result);
        assert!(settings.cloud_correction_enabled);
        assert!(settings.cloud_vocabulary.is_empty());
        // A settings.json written before the speech-filter toggle existed
        // must keep dropping silent uploads exactly as before.
        assert!(settings.cloud_speech_filter);

        let explicit = r#"{
            "hotkey": "XBUTTON2",
            "model": "parakeet-tdt-0.6b-v3-int8",
            "keepClipboardResult": false,
            "minimizeTray": true,
            "selectedDevice": "default",
            "selectedLanguage": "it",
            "computeDevice": "cpu",
            "holdToSpeak": false,
            "groqApiKey": "",
            "provider": "local"
        }"#;
        let disabled: AppSettings = serde_json::from_str(explicit).unwrap();
        assert!(!disabled.keep_clipboard_result);
    }

    #[test]
    fn test_settings_json_roundtrip() {
        let dir = std::env::temp_dir().join("traflix_test_settings");
        let _ = std::fs::create_dir_all(&dir);
        let path = dir.join("settings.json");

        // Write test settings
        let original = AppSettings {
            hotkey: "XBUTTON2".to_string(),
            secondary_hotkey: String::new(),
            model: "parakeet-tdt-0.6b-v3-int8".to_string(),
            auto_paste: None,
            keep_clipboard_result: true,
            minimize_tray: true,
            selected_device: "default".to_string(),
            selected_language: "it".to_string(),
            compute_device: "cpu".to_string(),
            hold_to_speak: false,
            groq_api_key: String::new(),
            provider: "local".to_string(),
            widget_mode: "always".to_string(),
            cloud_correction_enabled: false,
            cloud_vocabulary: "Example term".to_string(),
            cloud_speech_filter: false,
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
        assert!(!loaded.cloud_correction_enabled);
        assert_eq!(loaded.cloud_vocabulary, "Example term");
        assert!(!loaded.cloud_speech_filter);

        // Modify and save again
        let modified = AppSettings {
            hotkey: "Control+Shift+A".to_string(),
            ..original
        };
        let json2 = serde_json::to_string_pretty(&modified).unwrap();
        atomic_write(&path, &json2).unwrap();

        let reloaded = load_settings_from_file(&path);
        assert_eq!(reloaded.hotkey, "Control+Shift+A");
        assert_eq!(reloaded.model, "parakeet-tdt-0.6b-v3-int8"); // unchanged

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
        assert_eq!(settings.model, "parakeet-tdt-0.6b-v3-int8");
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
        assert_eq!(settings.widget_mode, "always");
        assert!(settings.keep_clipboard_result);
        assert!(settings.cloud_speech_filter);

        // Round-trip back to JSON
        let serialized = serde_json::to_string(&settings).unwrap();
        assert!(serialized.contains("\"minimizeTray\""));
        assert!(serialized.contains("\"selectedDevice\""));
        assert!(serialized.contains("\"selectedLanguage\""));
        assert!(serialized.contains("\"computeDevice\""));
        assert!(serialized.contains("\"holdToSpeak\""));
        assert!(serialized.contains("\"autoPaste\""));
        assert!(serialized.contains("\"widgetMode\""));
        assert!(serialized.contains("\"keepClipboardResult\""));
        assert!(serialized.contains("\"cloudSpeechFilter\""));
    }

    #[test]
    fn test_hotkey_config_sync_atomic_ptr() {
        // Simulate what happens in the app: create, swap, and verify
        let ptr = std::sync::Arc::new(std::sync::atomic::AtomicPtr::new(Box::into_raw(Box::new(
            parse_hotkey("XBUTTON2"),
        ))));

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
