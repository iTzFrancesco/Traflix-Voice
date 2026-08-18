mod commands;
mod hotkey;
mod hotkey_runtime;
mod settings;
mod sidecar;
mod state;
mod window_runtime;

mod clipboard;

// Re-exports for compatibility — tests use `use super::*` and run() needs direct access
pub use commands::*;
pub use hotkey::is_key_pressed;
pub use hotkey::{parse_hotkey, str_to_vk};
pub use settings::*;
pub use state::*;

use log::info;
use std::fs;
use std::sync::atomic::AtomicBool;
#[cfg(test)]
use std::sync::atomic::Ordering;
use std::sync::{Arc, Mutex, RwLock};
use tauri::{Emitter, Manager};

// ─── ENTRY POINT ─────────────────────────────────────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = tauri::Builder::default()
        .setup(|app| {
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

            let settings = load_settings_from_file(&settings_path);
            let initial_config = [settings.hotkey.as_str(), settings.secondary_hotkey.as_str()]
                .into_iter()
                .filter(|hotkey| !hotkey.trim().is_empty())
                .map(parse_hotkey)
                .filter(|config| !config.vk_codes.is_empty())
                .collect::<Vec<_>>();
            info!("[Hotkey] Configurate: {:?}", initial_config);
            let hotkey_config = Arc::new(RwLock::new(initial_config));

            app.manage(AppState {
                stats: Mutex::new(load_stats_from_file(&stats_path)),
                python_process: Mutex::new(None),
                settings_path,
                stats_path,
                history_path,
                groq_usage_path: groq_usage_path.clone(),
                hotkey_config: hotkey_config.clone(),
                is_shutting_down: AtomicBool::new(false),
            });

            let app_handle = app.handle().clone();
            hotkey_runtime::spawn(app_handle.clone(), hotkey_config);

            #[cfg(debug_assertions)]
            let script_dir = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
            #[cfg(not(debug_assertions))]
            let script_dir = app
                .path()
                .resource_dir()
                .expect("Impossibile trovare resource dir");
            let script_path = script_dir.join("whisper_engine.py");
            sidecar::spawn(app_handle.clone(), script_path, models_dir.clone());

            // Emit initial widget mode for the overlay
            let _ = app.emit("widget_mode_updated", settings.widget_mode.clone());
            window_runtime::setup_tray(app)?;
            window_runtime::install_listeners(app);

            Ok(())
        })
        .on_window_event(window_runtime::handle_window_event)
        .plugin(tauri_plugin_log::Builder::new().build())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_opener::init());

    #[cfg(not(debug_assertions))]
    let builder = builder.plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
        window_runtime::show_main_window(app);
    }));

    builder
        .invoke_handler(tauri::generate_handler![
            is_dev,
            load_settings,
            save_settings,
            get_stats,
            update_stats,
            get_audio_devices,
            send_to_python,
            stop_python,
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
        assert_eq!(settings.widget_mode, "always");

        // Round-trip back to JSON
        let serialized = serde_json::to_string(&settings).unwrap();
        assert!(serialized.contains("\"minimizeTray\""));
        assert!(serialized.contains("\"selectedDevice\""));
        assert!(serialized.contains("\"selectedLanguage\""));
        assert!(serialized.contains("\"computeDevice\""));
        assert!(serialized.contains("\"holdToSpeak\""));
        assert!(serialized.contains("\"autoPaste\""));
        assert!(serialized.contains("\"widgetMode\""));
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
