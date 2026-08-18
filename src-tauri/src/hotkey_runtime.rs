use log::debug;
use std::sync::{Arc, RwLock};
use std::thread;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter, Runtime};

use crate::hotkey::is_key_pressed;
use crate::state::HotkeyConfig;

const POLL_INTERVAL: Duration = Duration::from_millis(8);
const EMIT_DEBOUNCE: Duration = Duration::from_millis(100);

/// Start the process-wide hotkey polling loop.
///
/// The loop intentionally owns no application state beyond the shared
/// configuration and emits the same events consumed by the frontend.
pub fn spawn<R: Runtime>(app_handle: AppHandle<R>, hotkey_config: Arc<RwLock<Vec<HotkeyConfig>>>) {
    thread::spawn(move || {
        let mut hotkey_active = false;
        let mut last_emit = Instant::now();

        loop {
            thread::sleep(POLL_INTERVAL);

            let config = hotkey_config.read().unwrap();
            if config.is_empty() {
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
