use log::{error, info, warn};
use std::path::PathBuf;
use std::sync::atomic::Ordering;
use std::thread;
use std::time::Duration;
use tauri::{AppHandle, Emitter, Manager, Runtime};
use tauri_plugin_shell::process::CommandEvent;
use tauri_plugin_shell::ShellExt;

use crate::settings::load_settings_from_file;
use crate::state::AppState;

const MAX_BACKOFF_SECS: u64 = 10;

fn is_volume_event(line: &str) -> bool {
    line.starts_with(r#"{"status":"volume""#) || line.starts_with(r#"{"status": "volume""#)
}

/// Start the Python sidecar supervisor.
///
/// The supervisor owns spawn, init, stdout forwarding, restart backoff and
/// intentional-shutdown detection. Its only external contract is the
/// `AppState` child slot and the existing frontend events.
pub fn spawn<R: Runtime>(app_handle: AppHandle<R>, script_path: PathBuf, models_dir: PathBuf) {
    let script_path_str = script_path.to_string_lossy().to_string();
    let models_dir_str = models_dir.to_string_lossy().to_string();
    info!("[Python sidecar] Script path: {}", script_path_str);

    thread::spawn(move || {
        let mut restart_count: u32 = 0;

        loop {
            {
                let state = app_handle.state::<AppState>();
                let _process_lock = state.python_process.lock().unwrap();
                if state.is_shutting_down.load(Ordering::SeqCst) {
                    break;
                }
                state.python_process_exited.store(false, Ordering::SeqCst);
            }

            info!(
                "[Python sidecar] Spawning python process (attempt #{})",
                restart_count + 1
            );

            let shell = app_handle.shell();
            let spawn_result =
                if script_path.extension().and_then(|ext| ext.to_str()) == Some("exe") {
                    shell.command(&script_path_str).spawn()
                } else {
                    // Development and non-Windows builds continue to run the
                    // Python entry point directly.
                    let python_cmd = if cfg!(windows) { "py" } else { "python3" };
                    let first_attempt = shell.command(python_cmd).args([&script_path_str]).spawn();
                    if first_attempt.is_err() {
                        warn!(
                            "[Python sidecar] {:?} not found, trying 'python'",
                            python_cmd
                        );
                        shell.command("python").args([&script_path_str]).spawn()
                    } else {
                        first_attempt
                    }
                };

            let (mut rx, mut child) = match spawn_result {
                Ok(pair) => pair,
                Err(e) => {
                    error!("[Python sidecar] Failed to spawn: {:?}", e);
                    app_handle
                        .state::<AppState>()
                        .python_process_exited
                        .store(true, Ordering::SeqCst);
                    sleep_before_restart(restart_count);
                    restart_count += 1;
                    continue;
                }
            };

            let settings = {
                let app_state = app_handle.state::<AppState>();
                load_settings_from_file(&app_state.settings_path)
            };
            let init_msg = serde_json::json!({
                "command": "init",
                "models_dir": models_dir_str,
                "compute_device": settings.compute_device,
                "model": settings.model,
                "groq_api_key": settings.groq_api_key,
                "provider": settings.provider,
                "cloud_correct_uncertain": settings.cloud_correction_enabled,
                "cloud_vocabulary": settings.cloud_vocabulary,
                "cloud_speech_filter": settings.cloud_speech_filter,
            });
            let _ =
                child.write(format!("{}\n", serde_json::to_string(&init_msg).unwrap()).as_bytes());

            *app_handle
                .state::<AppState>()
                .python_process
                .lock()
                .unwrap() = Some(child);

            if app_handle
                .state::<AppState>()
                .is_shutting_down
                .load(Ordering::SeqCst)
            {
                if let Some(child) = app_handle
                    .state::<AppState>()
                    .python_process
                    .lock()
                    .unwrap()
                    .take()
                {
                    let _ = child.kill();
                }
                while rx.blocking_recv().is_some() {}
                app_handle
                    .state::<AppState>()
                    .python_process_exited
                    .store(true, Ordering::SeqCst);
                break;
            }

            if restart_count > 0 {
                warn!(
                    "[Python sidecar] Process restarted (restart #{})",
                    restart_count
                );
                let _ = app_handle.emit("python_restarted", restart_count);
            }

            while let Some(event) = rx.blocking_recv() {
                if let CommandEvent::Stdout(line) = event {
                    let output = String::from_utf8_lossy(&line);
                    let output_str = output.as_ref();
                    if is_volume_event(output_str) {
                        // The main window does not consume meter events. Keep
                        // the high-frequency cloud stream in the overlay only
                        // instead of waking both WebViews for every block.
                        // If the overlay has already been destroyed, retain
                        // the old broadcast behavior so the sidecar stream
                        // remains observable during shutdown/reload races.
                        if app_handle
                            .emit_to("overlay", "python_output", output_str)
                            .is_err()
                        {
                            let _ = app_handle.emit("python_output", output_str);
                        }
                    } else {
                        let _ = app_handle.emit("python_output", output_str);
                    }
                }
            }

            *app_handle
                .state::<AppState>()
                .python_process
                .lock()
                .unwrap() = None;
            app_handle
                .state::<AppState>()
                .python_process_exited
                .store(true, Ordering::SeqCst);

            if app_handle
                .state::<AppState>()
                .is_shutting_down
                .load(Ordering::SeqCst)
            {
                info!("[Python sidecar] Process exited (intentional shutdown)");
                break;
            }
            error!("[Python sidecar] Process exited unexpectedly, will restart");

            restart_count += 1;
            sleep_before_restart(restart_count);
        }
    });
}

/// Stop recording and then ask the sidecar to quit, preserving the existing
/// delays that give each command time to reach the child process.
pub fn shutdown<R: Runtime>(app_handle: &AppHandle<R>) -> Result<(), String> {
    let state = app_handle.state::<AppState>();
    {
        let _process_lock = state.python_process.lock().unwrap();
        state.is_shutting_down.store(true, Ordering::SeqCst);
    }

    {
        let mut process = state.python_process.lock().unwrap();
        if let Some(child) = process.as_mut() {
            let _ = child.write(b"{\"command\": \"stop\"}\n");
        }
    }
    thread::sleep(Duration::from_millis(300));

    {
        let mut process = state.python_process.lock().unwrap();
        if let Some(child) = process.as_mut() {
            let _ = child.write(b"{\"command\": \"quit\"}\n");
        }
    }

    if wait_for_process_exit(&state.python_process_exited, Duration::from_millis(1200)) {
        return Ok(());
    }

    let child = state.python_process.lock().unwrap().take();
    if let Some(child) = child {
        child.kill().map_err(|error| {
            format!("Impossibile terminare il motore Python prima dell'aggiornamento: {error}")
        })?;
    }

    if wait_for_process_exit(&state.python_process_exited, Duration::from_millis(1500)) {
        Ok(())
    } else {
        Err("Il motore Python non si è arrestato: aggiornamento annullato".to_string())
    }
}

fn wait_for_process_exit(exited: &std::sync::atomic::AtomicBool, timeout: Duration) -> bool {
    let deadline = std::time::Instant::now() + timeout;
    while !exited.load(Ordering::SeqCst) {
        if std::time::Instant::now() >= deadline {
            return false;
        }
        thread::sleep(Duration::from_millis(20));
    }
    true
}

fn sleep_before_restart(restart_count: u32) {
    let delay = std::cmp::min(2u64.saturating_pow(restart_count), MAX_BACKOFF_SECS);
    if restart_count > 0 {
        info!("[Python sidecar] Waiting {}s before restart...", delay);
    }
    thread::sleep(Duration::from_secs(delay));
}

#[cfg(test)]
mod tests {
    use super::is_volume_event;

    #[test]
    fn routes_compact_and_legacy_volume_lines() {
        assert!(is_volume_event(r#"{"status":"volume","value":42}"#));
        assert!(is_volume_event(r#"{"status": "volume", "value": 42}"#));
        assert!(!is_volume_event(r#"{"status":"result","text":"ok"}"#));
    }
}
