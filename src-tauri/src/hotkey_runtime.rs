use log::debug;
use std::sync::{Arc, RwLock};
use std::thread;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter, Runtime};

use crate::hotkey::is_key_pressed;
use crate::state::HotkeyConfig;

// Keep the cloud record/stop gesture responsive without waking the process at
// 250 Hz while idle. The existing polling implementation remains unchanged.
const POLL_INTERVAL: Duration = Duration::from_millis(8);
// The active-state latch already suppresses repeats while a button is held;
// keep only a short switch-bounce guard so a stop followed by a new cloud
// recording is not artificially delayed by 100 ms.
const EMIT_DEBOUNCE: Duration = Duration::from_millis(32);

/// Start the process-wide hotkey polling loop.
///
/// The loop intentionally owns no application state beyond the shared
/// configuration and emits the same events consumed by the frontend.
pub fn spawn<R: Runtime>(app_handle: AppHandle<R>, hotkey_config: Arc<RwLock<Vec<HotkeyConfig>>>) {
    thread::spawn(move || {
        let mut hotkey_active = false;
        // Allow the first valid press immediately after startup instead of
        // inheriting the debounce window from thread creation.
        let mut last_emit = Instant::now() - EMIT_DEBOUNCE;

        loop {
            thread::sleep(POLL_INTERVAL);

            let config = hotkey_config.read().unwrap();
            if config.is_empty() {
                // A malformed/cleared configuration must not leave hold-to-
                // speak stuck in the active state forever.
                if hotkey_active {
                    hotkey_active = false;
                    let _ = app_handle.emit("hotkey_released", ());
                }
                drop(config);
                continue;
            }
            let all_pressed = config
                .iter()
                .any(|hotkey| hotkey.vk_codes.iter().all(|&vk| is_key_pressed(vk)));
            drop(config);

            if all_pressed && !hotkey_active && last_emit.elapsed() > EMIT_DEBOUNCE {
                hotkey_active = true;
                last_emit = Instant::now();
                debug!("[Hotkey] Pressed");
                let _ = app_handle.emit("hotkey_pressed", ());
            } else if !all_pressed && hotkey_active {
                hotkey_active = false;
                debug!("[Hotkey] Released");
                let _ = app_handle.emit("hotkey_released", ());
            }
        }
    });
}
