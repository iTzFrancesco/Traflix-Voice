#[cfg(windows)]
use windows_sys::Win32::UI::Input::KeyboardAndMouse::GetAsyncKeyState;

use crate::state::HotkeyConfig;

pub fn parse_hotkey(hotkey: &str) -> HotkeyConfig {
    let mut vk_codes = Vec::new();
    for part in hotkey.split('+') {
        if let Some(vk) = str_to_vk(part) {
            vk_codes.push(vk);
        }
    }
    HotkeyConfig { vk_codes }
}

pub fn str_to_vk(s: &str) -> Option<i32> {
    match s {
        "CommandOrControl" | "Control" | "Ctrl" => Some(0x11), // VK_CONTROL
        "Alt" => Some(0x12),                                   // VK_MENU
        "AltGraph" => Some(0xA5),                              // VK_RMENU (right Alt / AltGr)
        "Shift" => Some(0x10),                                 // VK_SHIFT
        "Super" | "Meta" => Some(0x5B),                        // VK_LWIN
        "Space" => Some(0x20),                                 // VK_SPACE
        "Enter" | "Return" => Some(0x0D),
        "Tab" => Some(0x09),
        "Escape" | "Esc" => Some(0x1B),
        "Backspace" => Some(0x08),
        "Delete" => Some(0x2E),
        "Up" | "ArrowUp" => Some(0x26),
        "Down" | "ArrowDown" => Some(0x28),
        "Left" | "ArrowLeft" => Some(0x25),
        "Right" | "ArrowRight" => Some(0x27),
        "F1" => Some(0x70),
        "F2" => Some(0x71),
        "F3" => Some(0x72),
        "F4" => Some(0x73),
        "F5" => Some(0x74),
        "F6" => Some(0x75),
        "F7" => Some(0x76),
        "F8" => Some(0x77),
        "F9" => Some(0x78),
        "F10" => Some(0x79),
        "F11" => Some(0x7A),
        "F12" => Some(0x7B),
        "A" => Some(0x41),
        "B" => Some(0x42),
        "C" => Some(0x43),
        "D" => Some(0x44),
        "E" => Some(0x45),
        "F" => Some(0x46),
        "G" => Some(0x47),
        "H" => Some(0x48),
        "I" => Some(0x49),
        "J" => Some(0x4A),
        "K" => Some(0x4B),
        "L" => Some(0x4C),
        "M" => Some(0x4D),
        "N" => Some(0x4E),
        "O" => Some(0x4F),
        "P" => Some(0x50),
        "Q" => Some(0x51),
        "R" => Some(0x52),
        "S" => Some(0x53),
        "T" => Some(0x54),
        "U" => Some(0x55),
        // Italian layout key next to M (VK_OEM_102 / ISO backslash key).
        // Older versions stored its localized label as "Ù".
        "Ù" => Some(0xE2),
        "V" => Some(0x56),
        "W" => Some(0x57),
        "X" => Some(0x58),
        "Y" => Some(0x59),
        "Z" => Some(0x5A),
        "0" => Some(0x30),
        "1" => Some(0x31),
        "2" => Some(0x32),
        "3" => Some(0x33),
        "4" => Some(0x34),
        "5" => Some(0x35),
        "6" => Some(0x36),
        "7" => Some(0x37),
        "8" => Some(0x38),
        "9" => Some(0x39),
        // Pulsanti laterali del mouse
        "XBUTTON1" | "XButton1" | "Mouse4" | "Back" => Some(0x05), // VK_XBUTTON1
        "XBUTTON2" | "XButton2" | "Mouse5" | "Forward" => Some(0x06), // VK_XBUTTON2
        "MButton" | "Middle" => Some(0x04),                        // VK_MBUTTON
        _ => None,
    }
}

#[cfg(windows)]
pub fn is_key_pressed(vk: i32) -> bool {
    unsafe { GetAsyncKeyState(vk) & (0x8000u16 as i16) != 0 }
}

#[cfg(not(windows))]
pub fn is_key_pressed(_vk: i32) -> bool {
    false
}
