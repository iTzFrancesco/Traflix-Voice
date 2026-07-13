#[cfg(windows)]
pub fn simulate_ctrl_v() {
    use windows_sys::Win32::UI::Input::KeyboardAndMouse::{
        SendInput, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT, KEYEVENTF_KEYUP, VK_CONTROL, VK_V,
    };

    fn make_kbd(w_vk: u16, dw_flags: u32) -> INPUT {
        INPUT {
            r#type: INPUT_KEYBOARD,
            Anonymous: INPUT_0 { ki: KEYBDINPUT {
                wVk: w_vk,
                wScan: 0,
                dwFlags: dw_flags,
                time: 0,
                dwExtraInfo: 0,
            }},
        }
    }

    let inputs = [
        make_kbd(VK_CONTROL, 0),           // Ctrl down
        make_kbd(VK_V, 0),                 // V down
        make_kbd(VK_V, KEYEVENTF_KEYUP),   // V up
        make_kbd(VK_CONTROL, KEYEVENTF_KEYUP), // Ctrl up
    ];

    unsafe {
        SendInput(4, inputs.as_ptr(), std::mem::size_of::<INPUT>() as i32);
    }
}
