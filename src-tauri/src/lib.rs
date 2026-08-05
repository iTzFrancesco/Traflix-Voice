mod commands;
mod hotkey;
mod settings;
mod state;
mod voice_bridge;

#[cfg(windows)]
mod clipboard;

// Re-exports for compatibility — tests use `use super::*` and run() needs direct access
pub use commands::*;
#[cfg(windows)]
pub use hotkey::is_key_pressed;
pub use hotkey::{parse_hotkey, str_to_vk};
pub use settings::*;
pub use state::*;

use log::{debug, error, info, warn};
use std::fs;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, RwLock};
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Emitter, Listener, Manager, WindowEvent,
};
use tauri_plugin_shell::ShellExt;

// ─── ENTRY POINT ─────────────────────────────────────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let space_integration_mode =
                std::env::args().any(|argument| argument == "--space-integration");
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
                models_dir: models_dir.clone(),
                groq_usage_path: groq_usage_path.clone(),
                hotkey_config: hotkey_config.clone(),
                is_shutting_down: AtomicBool::new(false),
            });
            app.manage(voice_bridge::VoiceBridgeState::new());
            voice_bridge::start(app.handle().clone());

            // Hotkey polling via GetAsyncKeyState (~60Hz, no hooks, no message pump)
            let app_handle_kb = app.handle().clone();
            std::thread::spawn(move || {
                let mut hotkey_active = false;
                let mut last_emit: std::time::Instant = std::time::Instant::now();

                loop {
                    std::thread::sleep(std::time::Duration::from_millis(16));

                    let config = hotkey_config.read().unwrap();
                    if config.is_empty() {
                        drop(config);
                        continue;
                    }
                    let all_pressed = config
                        .iter()
                        .any(|hotkey| hotkey.vk_codes.iter().all(|&vk| is_key_pressed(vk)));
                    drop(config);

                    if all_pressed
                        && !hotkey_active
                        && last_emit.elapsed() > std::time::Duration::from_millis(100)
                    {
                        hotkey_active = true;
                        last_emit = std::time::Instant::now();
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
            let app_handle_widget = app_handle.clone();
            let models_dir_str = models_dir.to_string_lossy().to_string();
            #[cfg(debug_assertions)]
            let script_dir = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
            #[cfg(not(debug_assertions))]
            let script_dir = app
                .path()
                .resource_dir()
                .expect("Impossibile trovare resource dir");
            let script_path = script_dir.join("whisper_engine.py");
            let script_path_str = script_path.to_string_lossy().to_string();
            info!("[Python sidecar] Script path: {}", script_path_str);

            std::thread::spawn(move || {
                let mut restart_count: u32 = 0;
                const MAX_BACKOFF_SECS: u64 = 10;

                loop {
                    info!(
                        "[Python sidecar] Spawning python process (attempt #{})",
                        restart_count + 1
                    );

                    let shell = app_handle.shell();
                    // Windows: prova "py" (Python launcher, sempre in PATH),
                    // poi "python" come fallback
                    let python_cmd = if cfg!(windows) { "py" } else { "python3" };
                    let spawn_result = shell.command(python_cmd).args([&script_path_str]).spawn();
                    // Fallback: se "py"/"python3" fallisce, prova "python"
                    #[allow(unused_assignments)]
                    let spawn_result = if spawn_result.is_err() {
                        warn!(
                            "[Python sidecar] {:?} not found, trying 'python'",
                            python_cmd
                        );
                        shell.command("python").args([&script_path_str]).spawn()
                    } else {
                        spawn_result
                    };

                    let (mut rx, mut child) = match spawn_result {
                        Ok(pair) => pair,
                        Err(e) => {
                            error!("[Python sidecar] Failed to spawn: {:?}", e);
                            let delay =
                                std::cmp::min(2u64.saturating_pow(restart_count), MAX_BACKOFF_SECS);
                            std::thread::sleep(std::time::Duration::from_secs(delay));
                            restart_count += 1;
                            continue;
                        }
                    };

                    // Send init command (models_dir + compute_device)
                    let (selected_model, compute_device, groq_api_key, provider) = {
                        let app_state = app_handle.state::<AppState>();
                        let s = load_settings_from_file(&app_state.settings_path);
                        (s.model, s.compute_device, s.groq_api_key, s.provider)
                    };
                    let init_msg = serde_json::json!({
                        "command": "init",
                        "models_dir": models_dir_str,
                        "compute_device": compute_device,
                        "model": selected_model,
                        "groq_api_key": groq_api_key,
                        "provider": provider,
                    });
                    let _ = child.write(
                        format!("{}\n", serde_json::to_string(&init_msg).unwrap()).as_bytes(),
                    );

                    // Store the child handle so send_to_python can write to it
                    *app_handle
                        .state::<AppState>()
                        .python_process
                        .lock()
                        .unwrap() = Some(child);

                    if restart_count > 0 {
                        warn!(
                            "[Python sidecar] Process restarted (restart #{})",
                            restart_count
                        );
                        let _ = app_handle.emit("python_restarted", restart_count);
                    }

                    // Read stdout until the process exits (rx channel closes)
                    while let Some(event) = rx.blocking_recv() {
                        if let tauri_plugin_shell::process::CommandEvent::Stdout(line) = event {
                            let line = String::from_utf8_lossy(&line).to_string();
                            let _ = app_handle.emit("python_output", line.clone());
                            voice_bridge::publish_python_output(&app_handle, &line);
                        }
                    }

                    // If we reach here, the Python process has died
                    // Skip restart if we're shutting down intentionally
                    if app_handle
                        .state::<AppState>()
                        .is_shutting_down
                        .load(Ordering::SeqCst)
                    {
                        info!("[Python sidecar] Process exited (intentional shutdown)");
                        break;
                    }
                    error!("[Python sidecar] Process exited unexpectedly, will restart");

                    // Clear the stale child handle
                    *app_handle
                        .state::<AppState>()
                        .python_process
                        .lock()
                        .unwrap() = None;

                    // Back-off before restarting
                    restart_count += 1;
                    let delay = std::cmp::min(2u64.saturating_pow(restart_count), MAX_BACKOFF_SECS);
                    info!("[Python sidecar] Waiting {}s before restart...", delay);
                    std::thread::sleep(std::time::Duration::from_secs(delay));
                }
            });

            // Emit initial widget mode for the overlay
            let _ = app_handle_widget.emit("widget_mode_updated", settings.widget_mode.clone());

            // Tray Menu
            let show_i =
                MenuItem::with_id(app, "show", "Mostra Traflix Voice", true, None::<&str>)?;
            let quit_i = MenuItem::with_id(app, "quit", "Esci", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show_i, &quit_i])?;

            let tray_tooltip = if cfg!(debug_assertions) {
                "Traflix Voice [DEV]"
            } else {
                "Traflix Voice"
            };

            let _tray = TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .tooltip(tray_tooltip)
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
                        // Mark as shutting down so the sidecar reader skips restart
                        handle
                            .state::<AppState>()
                            .is_shutting_down
                            .store(true, Ordering::SeqCst);
                        // Stop any active recording first, then quit cleanly
                        if let Some(child) = handle
                            .state::<AppState>()
                            .python_process
                            .lock()
                            .unwrap()
                            .as_mut()
                        {
                            let _ = child.write(b"{\"command\": \"stop\"}\n");
                        }
                        std::thread::sleep(std::time::Duration::from_millis(300));
                        if let Some(child) = handle
                            .state::<AppState>()
                            .python_process
                            .lock()
                            .unwrap()
                            .as_mut()
                        {
                            let _ = child.write(b"{\"command\": \"quit\"}\n");
                        }
                        std::thread::sleep(std::time::Duration::from_millis(500));
                        handle.exit(0);
                    }
                })
                .build(app)?;

            // Listen for show_main_window event from overlay
            let app_handle_show = app.handle().clone();

            // Listen for widget_mode updates from save_settings
            let app_handle_wm = app.handle().clone();
            app.listen("widget_mode_updated", move |event| {
                let mode: String = serde_json::from_str(event.payload()).unwrap_or_default();
                info!("[WidgetMode] Updated to: {}", mode);
                // If switching to "always", show overlay if main window is hidden
                if mode == "always" {
                    if let Some(main_win) = app_handle_wm.get_webview_window("main") {
                        let is_visible = main_win.is_visible().unwrap_or(false);
                        let bridge_attached = app_handle_wm
                            .state::<voice_bridge::VoiceBridgeState>()
                            .is_attached();
                        if !is_visible && !bridge_attached {
                            if let Some(overlay) = app_handle_wm.get_webview_window("overlay") {
                                let _ = overlay.show();
                            }
                        }
                    }
                }
                // If switching to "recording", hide overlay immediately
                if mode == "recording" {
                    if let Some(overlay) = app_handle_wm.get_webview_window("overlay") {
                        let _ = overlay.hide();
                    }
                }
            });

            app.listen("show_main_window", move |_| {
                if let Some(main_win) = app_handle_show.get_webview_window("main") {
                    let _ = main_win.show();
                    let _ = main_win.set_focus();
                }
                if let Some(overlay) = app_handle_show.get_webview_window("overlay") {
                    let _ = overlay.hide();
                }
            });

            // Space integration is opt-in. It only changes initial visibility;
            // Voice keeps the normal tray, hotkey, settings and engine paths.
            if space_integration_mode {
                if let Some(main_win) = app.get_webview_window("main") {
                    let _ = main_win.hide();
                }
                if let Some(overlay) = app.get_webview_window("overlay") {
                    let _ = overlay.hide();
                }
            }

            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == "main" {
                    api.prevent_close();
                    let _ = window.hide();
                    // Show the mini overlay widget only if widget mode is "always"
                    let app_handle = window.app_handle();
                    let app_state = app_handle.state::<AppState>();
                    let settings = load_settings_from_file(&app_state.settings_path);
                    let bridge_attached = app_handle
                        .state::<voice_bridge::VoiceBridgeState>()
                        .is_attached();
                    if settings.widget_mode == "always" && !bridge_attached {
                        if let Some(overlay) = app_handle.get_webview_window("overlay") {
                            let _ = overlay.show();
                            let _ = overlay.set_focus();
                        }
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
        .plugin(tauri_plugin_single_instance::init(|app, args, _cwd| {
            let integration_mode = args.iter().any(|arg| arg == "--space-integration");
            if let Some(main_win) = app.get_webview_window("main") {
                if integration_mode {
                    let _ = main_win.hide();
                } else {
                    let _ = main_win.show();
                    let _ = main_win.set_focus();
                }
            }
            if let Some(overlay) = app.get_webview_window("overlay") {
                let _ = overlay.hide();
            }
        }))
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
