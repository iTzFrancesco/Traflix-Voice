use log::info;
use serde::Deserialize;
use std::error::Error;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{
    App, AppHandle, Emitter, Listener, Manager, PhysicalPosition, Position, Runtime, Window,
    WindowEvent,
};

use crate::settings::load_settings_from_file;
use crate::sidecar;
use crate::state::AppState;

#[derive(Debug, Deserialize, Default)]
struct WidgetPositionPayload {
    x: Option<i32>,
    y: Option<i32>,
}

fn parse_widget_position(payload: &str) -> Option<(i32, i32)> {
    let position = serde_json::from_str::<WidgetPositionPayload>(payload).ok()?;
    Some((position.x?, position.y?))
}

pub fn setup_tray<R: Runtime>(app: &mut App<R>) -> Result<(), Box<dyn Error>> {
    let show_i = MenuItem::with_id(app, "show", "Mostra Traflix Voice", true, None::<&str>)?;
    let quit_i = MenuItem::with_id(app, "quit", "Esci", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show_i, &quit_i])?;

    let tray_tooltip = if cfg!(debug_assertions) {
        "Traflix Voice [DEV]"
    } else {
        "Traflix Voice"
    };

    TrayIconBuilder::new()
        .icon(app.default_window_icon().unwrap().clone())
        .tooltip(tray_tooltip)
        .menu(&menu)
        .on_menu_event(|handle, event| match event.id.as_ref() {
            "show" => show_main_window(handle),
            "quit" => {
                sidecar::shutdown(handle);
                handle.exit(0);
            }
            _ => {}
        })
        .build(app)?;

    Ok(())
}

pub fn install_listeners<R: Runtime>(app: &mut App<R>) {
    let app_handle_wm = app.handle().clone();
    app.listen("widget_mode_updated", move |event| {
        let mode: String = serde_json::from_str(event.payload()).unwrap_or_default();
        info!("[WidgetMode] Updated to: {}", mode);

        if mode == "always" {
            if let Some(main_win) = app_handle_wm.get_webview_window("main") {
                let is_visible = main_win.is_visible().unwrap_or(false);
                if !is_visible {
                    show_overlay_with_animation(&app_handle_wm);
                }
            }
        }
        if mode == "recording" {
            if let Some(overlay) = app_handle_wm.get_webview_window("overlay") {
                let _ = overlay.hide();
            }
        }
    });

    let app_handle_show = app.handle().clone();
    app.listen("show_main_window", move |event| {
        let widget_position = parse_widget_position(event.payload());
        show_main_window_at(&app_handle_show, widget_position);
    });
}

pub fn show_main_window<R: Runtime>(app_handle: &AppHandle<R>) {
    show_main_window_at(app_handle, None);
}

fn show_main_window_at<R: Runtime>(app_handle: &AppHandle<R>, widget_position: Option<(i32, i32)>) {
    if let Some(main_win) = app_handle.get_webview_window("main") {
        if let Some((x, y)) = widget_position {
            let _ = main_win.set_position(Position::Physical(PhysicalPosition::new(x, y)));
        }
        let _ = main_win.show();
        let _ = main_win.set_focus();
    }
    if let Some(overlay) = app_handle.get_webview_window("overlay") {
        let _ = overlay.hide();
    }
}

fn show_overlay_with_animation<R: Runtime>(app_handle: &AppHandle<R>) {
    if let Some(overlay) = app_handle.get_webview_window("overlay") {
        let _ = overlay.show();
        let _ = overlay.set_focus();
        let _ = app_handle.emit_to("overlay", "overlay_appearing", ());
    }
}

fn sync_overlay_position<R: Runtime>(app_handle: &AppHandle<R>, position: PhysicalPosition<i32>) {
    if let Some(overlay) = app_handle.get_webview_window("overlay") {
        let _ = overlay.set_position(Position::Physical(position));
    }
}

pub fn handle_window_event<R: Runtime>(window: &Window<R>, event: &WindowEvent) {
    if window.label() == "main" {
        if let WindowEvent::Moved(position) = event {
            let app_handle = window.app_handle();
            sync_overlay_position(&app_handle, PhysicalPosition::new(position.x, position.y));
            return;
        }
    }

    if let WindowEvent::CloseRequested { api, .. } = event {
        if window.label() == "main" {
            api.prevent_close();
            let _ = window.hide();

            let app_handle = window.app_handle();
            let app_state = app_handle.state::<AppState>();
            let settings = load_settings_from_file(&app_state.settings_path);
            if settings.widget_mode == "always" {
                if let Ok(position) = window.outer_position() {
                    sync_overlay_position(&app_handle, position);
                }
                show_overlay_with_animation(&app_handle);
            }
        } else if window.label() == "overlay" {
            api.prevent_close();
            let _ = window.hide();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::parse_widget_position;

    #[test]
    fn parses_physical_widget_position() {
        assert_eq!(
            parse_widget_position(r#"{"x":-120,"y":640}"#),
            Some((-120, 640))
        );
    }

    #[test]
    fn ignores_missing_or_invalid_widget_position() {
        assert_eq!(parse_widget_position(r#"{"x":12}"#), None);
        assert_eq!(parse_widget_position("not-json"), None);
    }
}
