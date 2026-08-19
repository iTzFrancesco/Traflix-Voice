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
            info!(
                "[Python sidecar] Spawning python process (attempt #{})",
                restart_count + 1
            );

            let shell = app_handle.shell();
            // Windows: use the Python launcher first, then fall back to the
            // regular executable. On other platforms prefer python3.
            let python_cmd = if cfg!(windows) { "py" } else { "python3" };
            let spawn_result = shell.command(python_cmd).args([&script_path_str]).spawn();
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
                    sleep_before_restart(restart_count);
                    restart_count += 1;
                    continue;
                }
            };

            let (selected_model, compute_device, groq_api_key, provider) = {
                let app_state = app_handle.state::<AppState>();
                let settings = load_settings_from_file(&app_state.settings_path);
                (
                    settings.model,
                    settings.compute_device,
                    settings.groq_api_key,
                    settings.provider,
                )
            };
            let init_msg = serde_json::json!({
                "command": "init",
                "models_dir": models_dir_str,
                "compute_device": compute_device,
                "model": selected_model,
                "groq_api_key": groq_api_key,
                "provider": provider,
            });
            let _ =
                child.write(format!("{}\n", serde_json::to_string(&init_msg).unwrap()).as_bytes());

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

            if app_handle
                .state::<AppState>()
                .is_shutting_down
                .load(Ordering::SeqCst)
            {
                info!("[Python sidecar] Process exited (intentional shutdown)");
                break;
            }
            error!("[Python sidecar] Process exited unexpectedly, will restart");

            *app_handle
                .state::<AppState>()
                .python_process
                .lock()
                .unwrap() = None;

            restart_count += 1;
            sleep_before_restart(restart_count);
        }
    });
}

/// Stop recording and then ask the sidecar to quit, preserving the existing
/// delays that give each command time to reach the child process.
pub fn shutdown<R: Runtime>(app_handle: &AppHandle<R>) {
    app_handle
        .state::<AppState>()
        .is_shutting_down
        .store(true, Ordering::SeqCst);

    if let Some(child) = app_handle
        .state::<AppState>()
        .python_process
        .lock()
        .unwrap()
        .as_mut()
    {
        let _ = child.write(b"{\"command\": \"stop\"}\n");
    }
    thread::sleep(Duration::from_millis(300));

    if let Some(child) = app_handle
        .state::<AppState>()
        .python_process
        .lock()
        .unwrap()
        .as_mut()
    {
        let _ = child.write(b"{\"command\": \"quit\"}\n");
    }
    thread::sleep(Duration::from_millis(500));
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
