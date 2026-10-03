//! Soppressione del comportamento di default dei pulsanti laterali del mouse.
//!
//! Su Windows `XBUTTON1`/`XBUTTON2` sono collegati ad Avanti/Indietro del
//! browser: il polling con `GetAsyncKeyState` rileva la pressione ma non la
//! consuma, quindi il browser naviga mentre Traflix registra (come Whisperflow
//! invece non deve accadere).
//!
//! Questo modulo installa un hook `WH_MOUSE_LL` che ingoia gli eventi dei
//! pulsanti configurati come hotkey. L'hook gira su un thread dedicato con
//! message pump; alla chiusura dell'app il thread muore, l'hook viene
//! rimosso e i pulsanti tornano al comportamento di sistema.
//!
//! La procedura di hook fa solo una `AtomicU8` load + confronti interi (mai
//! lock o allocazioni) per restare sotto il timeout `LowLevelHooksTimeout`.
//! La maschera viene aggiornata dal loop di polling esistente.

use std::sync::atomic::{AtomicBool, AtomicU8, Ordering};

use crate::state::HotkeyConfig;

/// Maschera di soppressione: quali pulsanti ingoiare quando premuti da soli.
pub const SUPPRESS_XBUTTON1: u8 = 0x01;
pub const SUPPRESS_XBUTTON2: u8 = 0x02;
pub const SUPPRESS_MBUTTON: u8 = 0x04;

/// Letta dalla procedura di hook senza lock; scritta dal loop di polling.
pub static SUPPRESS_MASK: AtomicU8 = AtomicU8::new(0);

/// Vera mentre le impostazioni stanno registrando un nuovo hotkey: l'hook
/// lascia passare i click così il WebView può catturare XBUTTON1/2 come
/// nuova scorciatoia. Muore col processo, quindi non può restare incastrata.
pub static CAPTURE_ACTIVE: AtomicBool = AtomicBool::new(false);

/// Chiamata dal comando Tauri `set_hotkey_capture_active`.
pub fn set_capture_active(active: bool) {
    CAPTURE_ACTIVE.store(active, Ordering::Relaxed);
}

/// Calcola la maschera dai soli hotkey composti da un singolo pulsante.
///
/// Solo gli hotkey "puri" (es. `XBUTTON2` da solo) sopprimono il pulsante: una
/// combinazione come `Ctrl+XBUTTON2` non deve ingoiare il click semplice senza
/// modificatori, altrimenti si romperebbe la navigazione quando l'hotkey non
/// scatta davvero.
pub fn mask_for_configs(configs: &[HotkeyConfig]) -> u8 {
    let mut mask = 0u8;
    for config in configs {
        if config.vk_codes.len() == 1 {
            match config.vk_codes[0] {
                0x05 => mask |= SUPPRESS_XBUTTON1, // VK_XBUTTON1
                0x06 => mask |= SUPPRESS_XBUTTON2, // VK_XBUTTON2
                0x04 => mask |= SUPPRESS_MBUTTON,  // VK_MBUTTON
                _ => {}
            }
        }
    }
    mask
}

/// Aggiorna la maschera letta dall'hook. Chiamata dal loop di polling.
pub fn refresh_from_configs(configs: &[HotkeyConfig]) {
    SUPPRESS_MASK.store(mask_for_configs(configs), Ordering::Relaxed);
}

/// Installa l'hook globale. Su Windows apre un thread con message pump;
/// altrove è un no-op.
#[cfg(windows)]
pub fn spawn() {
    let _ = std::thread::Builder::new()
        .name("mouse-suppress-hook".to_string())
        .spawn(|| unsafe {
            use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
            use windows_sys::Win32::UI::WindowsAndMessaging::{
                DispatchMessageW, GetMessageW, SetWindowsHookExW, TranslateMessage,
                UnhookWindowsHookEx, HHOOK, MSG, WH_MOUSE_LL,
            };

            let hook: HHOOK = SetWindowsHookExW(
                WH_MOUSE_LL,
                Some(hook_proc),
                GetModuleHandleW(std::ptr::null()),
                0,
            );
            if hook.is_null() {
                log::warn!("[Hotkey] Hook mouse non installato: XBUTTON resta navigazione browser");
                return;
            }
            log::info!("[Hotkey] Hook mouse attivo: XBUTTON configurati non navigano più");

            let mut msg: MSG = std::mem::zeroed();
            while GetMessageW(&mut msg, std::ptr::null_mut(), 0, 0) > 0 {
                TranslateMessage(&msg);
                DispatchMessageW(&msg);
            }
            UnhookWindowsHookEx(hook);
        });
}

#[cfg(not(windows))]
pub fn spawn() {}

/// Procedura `WH_MOUSE_LL`: ritorna 1 per ingoiare l'evento, altrimenti lo
/// inoltra con `CallNextHookEx`.
#[cfg(windows)]
unsafe extern "system" fn hook_proc(
    ncode: i32,
    wparam: windows_sys::Win32::Foundation::WPARAM,
    lparam: windows_sys::Win32::Foundation::LPARAM,
) -> windows_sys::Win32::Foundation::LRESULT {
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        CallNextHookEx, MSLLHOOKSTRUCT, WM_MBUTTONDBLCLK, WM_MBUTTONDOWN, WM_MBUTTONUP,
        WM_XBUTTONDBLCLK, WM_XBUTTONDOWN, WM_XBUTTONUP,
    };

    if ncode >= 0 && !CAPTURE_ACTIVE.load(Ordering::Relaxed) {
        let mask = SUPPRESS_MASK.load(Ordering::Relaxed);
        if mask != 0 {
            let msg = wparam as u32;
            let swallow = match msg {
                WM_XBUTTONDOWN | WM_XBUTTONUP | WM_XBUTTONDBLCLK => {
                    if lparam == 0 {
                        false
                    } else {
                        let xbutton = (((*(lparam as *const MSLLHOOKSTRUCT)).mouseData >> 16)
                            & 0xFFFF) as u16;
                        (xbutton == 1 && mask & SUPPRESS_XBUTTON1 != 0)
                            || (xbutton == 2 && mask & SUPPRESS_XBUTTON2 != 0)
                    }
                }
                WM_MBUTTONDOWN | WM_MBUTTONUP | WM_MBUTTONDBLCLK => mask & SUPPRESS_MBUTTON != 0,
                _ => false,
            };
            if swallow {
                return 1;
            }
        }
    }
    CallNextHookEx(std::ptr::null_mut(), ncode, wparam, lparam)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn single(vk: i32) -> HotkeyConfig {
        HotkeyConfig { vk_codes: vec![vk] }
    }

    #[test]
    fn suppresses_sole_xbutton_hotkeys() {
        assert_eq!(mask_for_configs(&[single(0x06)]), SUPPRESS_XBUTTON2);
        assert_eq!(mask_for_configs(&[single(0x05)]), SUPPRESS_XBUTTON1);
        assert_eq!(mask_for_configs(&[single(0x04)]), SUPPRESS_MBUTTON);
    }

    #[test]
    fn combines_primary_and_secondary_hotkeys() {
        let mask = mask_for_configs(&[single(0x06), single(0x05)]);
        assert_eq!(mask, SUPPRESS_XBUTTON1 | SUPPRESS_XBUTTON2);
    }

    #[test]
    fn ignores_combos_and_keyboard_keys() {
        // Ctrl+XBUTTON2 non deve ingoiare il click semplice senza Ctrl.
        let combo = HotkeyConfig {
            vk_codes: vec![0x11, 0x06],
        };
        assert_eq!(mask_for_configs(&[combo]), 0);
        assert_eq!(mask_for_configs(&[single(0x20)]), 0);
        assert_eq!(mask_for_configs(&[]), 0);
    }

    #[test]
    fn refresh_updates_shared_mask() {
        refresh_from_configs(&[single(0x06)]);
        assert_eq!(SUPPRESS_MASK.load(Ordering::Relaxed), SUPPRESS_XBUTTON2);
        refresh_from_configs(&[]);
        assert_eq!(SUPPRESS_MASK.load(Ordering::Relaxed), 0);
    }

    #[test]
    fn capture_flag_toggles_without_touching_mask() {
        assert!(!CAPTURE_ACTIVE.load(Ordering::Relaxed));
        set_capture_active(true);
        assert!(CAPTURE_ACTIVE.load(Ordering::Relaxed));
        // La maschera resta quella calcolata dagli hotkey salvati.
        refresh_from_configs(&[single(0x06)]);
        assert_eq!(SUPPRESS_MASK.load(Ordering::Relaxed), SUPPRESS_XBUTTON2);
        set_capture_active(false);
        assert!(!CAPTURE_ACTIVE.load(Ordering::Relaxed));
        refresh_from_configs(&[]);
    }
}
