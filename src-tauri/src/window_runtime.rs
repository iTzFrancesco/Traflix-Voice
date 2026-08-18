use log::info;
use std::error::Error;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{App, AppHandle, Listener, Manager, Runtime, Window, WindowEvent};

use crate::settings::load_settings_from_file;
use crate::sidecar;
use crate::state::AppState;

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
                    if let Some(overlay) = app_handle_wm.get_webview_window("overlay") {
                        let _ = overlay.show();
                    }
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
    app.listen("show_main_window", move |_| {
        show_main_window(&app_handle_show);
    });
}

pub fn show_main_window<R: Runtime>(app_handle: &AppHandle<R>) {
    if let Some(main_win) = app_handle.get_webview_window("main") {
        let _ = main_win.show();
        let _ = main_win.set_focus();
    }
    if let Some(overlay) = app_handle.get_webview_window("overlay") {
        let _ = overlay.hide();
    }
}

pub fn handle_window_event<R: Runtime>(window: &Window<R>, event: &WindowEvent) {
    if let WindowEvent::CloseRequested { api, .. } = event {
        if window.label() == "main" {
            api.prevent_close();
            let _ = window.hide();

            let app_handle = window.app_handle();
            let app_state = app_handle.state::<AppState>();
            let settings = load_settings_from_file(&app_state.settings_path);
            if settings.widget_mode == "always" {
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
}
