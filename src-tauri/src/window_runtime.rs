use log::info;
use serde::Deserialize;
use std::error::Error;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{
    App, AppHandle, Emitter, Listener, Manager, PhysicalPosition, Position, Runtime, WebviewWindow,
    Window, WindowEvent,
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
            // Il widget è piccolo (170x50), la dash è grande (450x650):
            // riusare x,y così com'è la spinge fuori schermo a bordo destro/basso.
            let (clamped_x, clamped_y) = clamp_main_window_position(&main_win, x, y);
            let _ = main_win.set_position(Position::Physical(PhysicalPosition::new(
                clamped_x, clamped_y,
            )));
        } else {
            ensure_main_window_visible(&main_win);
        }
        let _ = main_win.show();
        let _ = main_win.set_focus();
    }
    if let Some(overlay) = app_handle.get_webview_window("overlay") {
        let _ = overlay.hide();
    }
}

fn clamp_to_work_area(
    desired: (i32, i32),
    window_size: (i32, i32),
    work_origin: (i32, i32),
    work_size: (i32, i32),
) -> (i32, i32) {
    let (desired_x, desired_y) = desired;
    let (win_w, win_h) = window_size;
    let (work_x, work_y) = work_origin;
    let (work_w, work_h) = work_size;
    if work_w <= 0 || work_h <= 0 || win_w <= 0 || win_h <= 0 {
        return (desired_x, desired_y);
    }
    let clamped_x = if win_w >= work_w {
        work_x
    } else {
        desired_x.clamp(work_x, work_x + work_w - win_w)
    };
    let clamped_y = if win_h >= work_h {
        work_y
    } else {
        desired_y.clamp(work_y, work_y + work_h - win_h)
    };
    (clamped_x, clamped_y)
}

fn clamp_main_window_position<R: Runtime>(
    main_win: &WebviewWindow<R>,
    desired_x: i32,
    desired_y: i32,
) -> (i32, i32) {
    let (win_w, win_h) = main_win
        .outer_size()
        .map(|size| (size.width as i32, size.height as i32))
        .unwrap_or_else(|_| {
            let scale = main_win.scale_factor().unwrap_or(1.0);
            (
                (450.0 * scale).round() as i32,
                (650.0 * scale).round() as i32,
            )
        });

    let monitor = main_win
        .monitor_from_point(desired_x as f64, desired_y as f64)
        .ok()
        .flatten()
        .or_else(|| main_win.current_monitor().ok().flatten())
        .or_else(|| main_win.primary_monitor().ok().flatten())
        .or_else(|| {
            main_win
                .available_monitors()
                .ok()
                .and_then(|monitors| monitors.into_iter().next())
        });

    let Some(monitor) = monitor else {
        return (desired_x, desired_y);
    };

    let work_area = monitor.work_area();
    let (mut work_x, mut work_y, mut work_w, mut work_h) = (
        work_area.position.x,
        work_area.position.y,
        work_area.size.width as i32,
        work_area.size.height as i32,
    );
    if work_w <= 0 || work_h <= 0 {
        work_x = monitor.position().x;
        work_y = monitor.position().y;
        work_w = monitor.size().width as i32;
        work_h = monitor.size().height as i32;
    }

    clamp_to_work_area(
        (desired_x, desired_y),
        (win_w, win_h),
        (work_x, work_y),
        (work_w, work_h),
    )
}

fn ensure_main_window_visible<R: Runtime>(main_win: &WebviewWindow<R>) {
    let Ok(position) = main_win.outer_position() else {
        return;
    };
    let (clamped_x, clamped_y) = clamp_main_window_position(main_win, position.x, position.y);
    if clamped_x != position.x || clamped_y != position.y {
        let _ = main_win.set_position(Position::Physical(PhysicalPosition::new(
            clamped_x, clamped_y,
        )));
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
            sync_overlay_position(app_handle, PhysicalPosition::new(position.x, position.y));
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
                    sync_overlay_position(app_handle, position);
                }
                show_overlay_with_animation(app_handle);
            }
        } else if window.label() == "overlay" {
            api.prevent_close();
            let _ = window.hide();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{clamp_to_work_area, parse_widget_position};

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

    #[test]
    fn keeps_fully_visible_position_unchanged() {
        assert_eq!(
            clamp_to_work_area((100, 100), (450, 650), (0, 0), (1920, 1040)),
            (100, 100)
        );
    }

    #[test]
    fn clamps_widget_at_right_edge_so_main_stays_on_screen() {
        // 1920px wide work area, 450px wide main window: max x is 1470.
        assert_eq!(
            clamp_to_work_area((1790, 200), (450, 650), (0, 0), (1920, 1040)),
            (1470, 200)
        );
    }

    #[test]
    fn clamps_widget_at_bottom_edge_so_main_stays_on_screen() {
        // 1040px tall work area, 650px tall main window: max y is 390.
        assert_eq!(
            clamp_to_work_area((200, 990), (450, 650), (0, 0), (1920, 1040)),
            (200, 390)
        );
    }

    #[test]
    fn clamps_negative_position_to_work_area_origin() {
        assert_eq!(
            clamp_to_work_area((-120, -40), (450, 650), (0, 0), (1920, 1040)),
            (0, 0)
        );
    }

    #[test]
    fn aligns_to_work_area_when_window_larger_than_screen() {
        assert_eq!(
            clamp_to_work_area((1790, 900), (2000, 1200), (0, 0), (1920, 1040)),
            (0, 0)
        );
    }

    #[test]
    fn clamps_to_secondary_monitor_with_negative_origin() {
        // Secondario a sinistra del primario: origine -1920, largo 1920.
        // x=-100 sfora a destra (max -450).
        assert_eq!(
            clamp_to_work_area((-100, 100), (450, 650), (-1920, 0), (1920, 1040)),
            (-450, 100)
        );
    }
}
