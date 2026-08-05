use std::sync::atomic::{AtomicBool, Ordering};

use serde_json::{json, Value};
use tauri::{AppHandle, Manager};
use tokio::sync::broadcast;

pub const BRIDGE_PROTOCOL: u8 = 1;

#[cfg(debug_assertions)]
pub const PIPE_NAME: &str = r"\\.\pipe\traflix-voice-bridge-dev";
#[cfg(not(debug_assertions))]
pub const PIPE_NAME: &str = r"\\.\pipe\traflix-voice-bridge";

pub struct VoiceBridgeState {
    pub tx: broadcast::Sender<String>,
    attached: AtomicBool,
}

impl VoiceBridgeState {
    pub fn new() -> Self {
        let (tx, _) = broadcast::channel(64);
        Self {
            tx,
            attached: AtomicBool::new(false),
        }
    }

    pub fn set_attached(&self, value: bool) {
        self.attached.store(value, Ordering::Release);
    }

    pub fn is_attached(&self) -> bool {
        self.attached.load(Ordering::Acquire)
    }
}

pub fn start(app: AppHandle) {
    #[cfg(windows)]
    {
        tauri::async_runtime::spawn(async move {
            if let Err(error) = run_server(app).await {
                log::warn!("[VoiceBridge] Server stopped: {error}");
            }
        });
    }

    #[cfg(not(windows))]
    {
        let _ = app;
    }
}

pub fn publish_python_output<R: tauri::Runtime>(app: &AppHandle<R>, line: &str) {
    let Ok(payload) = serde_json::from_str::<Value>(line.trim()) else {
        return;
    };

    let Some(status) = payload.get("status").and_then(Value::as_str) else {
        return;
    };

    let event = match status {
        "listening" => json!({
            "type": "state",
            "state": "recording",
            "volume": 0,
        }),
        "processing" => json!({
            "type": "state",
            "state": "processing",
            "volume": 0,
        }),
        "volume" => json!({
            "type": "volume",
            "value": payload.get("value").and_then(Value::as_f64).unwrap_or(0.0),
        }),
        "result" | "ready" | "error" | "rate_limit" => json!({
            "type": "state",
            "state": "idle",
            "volume": 0,
        }),
        _ => return,
    };

    publish(app, event);
}

pub fn publish<R: tauri::Runtime>(app: &AppHandle<R>, event: Value) {
    let Ok(message) = serde_json::to_string(&event) else {
        return;
    };
    let _ = app.state::<VoiceBridgeState>().tx.send(message);
}

#[cfg(windows)]
async fn run_server(app: AppHandle) -> std::io::Result<()> {
    use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
    use tokio::net::windows::named_pipe::ServerOptions;

    let mut server = ServerOptions::new().create(PIPE_NAME)?;
    log::info!("[VoiceBridge] Listening on {PIPE_NAME}");

    loop {
        server.connect().await?;
        let connected = server;
        server = ServerOptions::new().create(PIPE_NAME)?;

        let client_app = app.clone();
        tauri::async_runtime::spawn(async move {
            let (reader, mut writer) = tokio::io::split(connected);
            let mut lines = BufReader::new(reader).lines();
            let mut events = client_app.state::<VoiceBridgeState>().tx.subscribe();

            let hello = json!({
                "type": "hello",
                "protocol": BRIDGE_PROTOCOL,
                "version": env!("CARGO_PKG_VERSION"),
            });
            if write_message(&mut writer, &hello).await.is_err() {
                return;
            }
            let _ = write_message(
                &mut writer,
                &json!({ "type": "state", "state": "idle", "volume": 0 }),
            )
            .await;

            loop {
                tokio::select! {
                    incoming = lines.next_line() => {
                        match incoming {
                            Ok(Some(line)) => handle_command(&client_app, line.trim()),
                            Ok(None) | Err(_) => break,
                        }
                    }
                    event = events.recv() => {
                        match event {
                            Ok(message) => {
                                if writer.write_all(message.as_bytes()).await.is_err()
                                    || writer.write_all(b"\n").await.is_err()
                                {
                                    break;
                                }
                            }
                            Err(broadcast::error::RecvError::Lagged(_)) => continue,
                            Err(broadcast::error::RecvError::Closed) => break,
                        }
                    }
                }
            }

            restore_standalone_overlay(&client_app);
        });
    }
}

#[cfg(windows)]
async fn write_message<W>(writer: &mut W, value: &Value) -> std::io::Result<()>
where
    W: tokio::io::AsyncWrite + Unpin,
{
    use tokio::io::AsyncWriteExt;

    let message = serde_json::to_string(value).map_err(std::io::Error::other)?;
    writer.write_all(message.as_bytes()).await?;
    writer.write_all(b"\n").await
}

#[cfg(windows)]
fn handle_command(app: &AppHandle, line: &str) {
    let Ok(command) = serde_json::from_str::<Value>(line) else {
        return;
    };

    match command.get("type").and_then(Value::as_str) {
        Some("attach") => {
            app.state::<VoiceBridgeState>().set_attached(true);
            if let Some(overlay) = app.get_webview_window("overlay") {
                let _ = overlay.hide();
            }
        }
        Some("show_main") => {
            if let Some(main) = app.get_webview_window("main") {
                let _ = main.show();
                let _ = main.set_focus();
            }
            if let Some(overlay) = app.get_webview_window("overlay") {
                let _ = overlay.hide();
            }
        }
        Some("detach") => restore_standalone_overlay(app),
        Some("ping") => publish(app, json!({ "type": "pong" })),
        _ => {}
    }
}

#[cfg(windows)]
fn restore_standalone_overlay(app: &AppHandle) {
    app.state::<VoiceBridgeState>().set_attached(false);
    let app_state = app.state::<crate::AppState>();
    let settings = crate::load_settings_from_file(&app_state.settings_path);
    if settings.widget_mode != "always" {
        return;
    }

    let Some(main) = app.get_webview_window("main") else {
        return;
    };
    if main.is_visible().unwrap_or(false) {
        return;
    }

    if let Some(overlay) = app.get_webview_window("overlay") {
        let _ = overlay.show();
    }
}
