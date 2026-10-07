import pytest
from playwright.sync_api import sync_playwright


TAURI_MOCK = r"""
(() => {
  const listeners = new Map(), calls = [];
  const state = {listeners, calls, visible: false,
    emit(name, payload) {
      for (const callback of listeners.get(name) || []) callback({payload});
    }};
  window.__overlayE2e = state;
  HTMLMediaElement.prototype.play = function() {
    calls.push({command: "sound", src: this.src});
    return Promise.resolve();
  };
  const currentWindow = {
    async show() { state.visible = true; calls.push({command: "show"}); },
    async hide() { state.visible = false; calls.push({command: "hide"}); },
    async startDragging() {},
    async outerPosition() { return {x: 0, y: 0}; },
  };
  window.__TAURI__ = {
    core: {async invoke(command) {
      return command === "load_settings" ? {widgetMode: "recording", provider: "local"} : false;
    }},
    app: {async getVersion() { return "overlay-e2e"; }},
    window: {getCurrentWindow() { return currentWindow; }},
    event: {
      async listen(name, callback) {
        const callbacks = listeners.get(name) || [];
        callbacks.push(callback);
        listeners.set(name, callbacks);
        return () => listeners.set(name, callbacks.filter(item => item !== callback));
      },
      async emit(name, payload) { state.emit(name, payload); },
    },
  };
})();
"""


ENTRY_FRAMES = r"""
async () => {
  window.__overlayE2e.emit("python_output", '{"status":"listening"}');
  await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  const animations = document.getAnimations();
  animations.forEach(animation => animation.pause());
  return [0, 16, 50, 100, 200, 244, 300, 420].map(ms => {
    animations.forEach(animation => animation.currentTime = ms);
    const widget = document.querySelector("#w").getBoundingClientRect();
    const label = document.querySelector(".lbl");
    return {ms, left: widget.left, right: widget.right,
      labelWidth: label.getBoundingClientRect().width,
      labelOpacity: Number(getComputedStyle(label).opacity)};
  });
}
"""


def open_overlay(browser, base_url, device_scale_factor=1):
    page = browser.new_page(
        viewport={"width": 170, "height": 50},
        device_scale_factor=device_scale_factor,
    )
    page.add_init_script(TAURI_MOCK)
    page.goto(f"{base_url}/overlay.html", wait_until="networkidle")
    page.wait_for_function("window.__overlayE2e.calls.some(call => call.command === 'hide')")
    return page


@pytest.mark.parametrize("show_dev_badge", [False, True])
@pytest.mark.parametrize("device_scale_factor", [1, 1.5, 2])
@pytest.mark.parametrize("status", ["listening", "processing"])
def test_overlay_entry_keeps_border_and_recording_layout_inside_window(
    e2e_base_url, show_dev_badge, device_scale_factor, status,
):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = open_overlay(browser, e2e_base_url, device_scale_factor)
            if not show_dev_badge:
                page.locator(".dev-slot").evaluate("slot => slot.replaceChildren()")
            frames = page.evaluate(ENTRY_FRAMES.replace('{"status":"listening"}',
                                                       '{"status":"' + status + '"}'))
            for frame in frames:
                assert frame["left"] >= 0, frame
                assert frame["right"] <= 170, frame
                assert frame["labelWidth"] == 0, frame
                assert frame["labelOpacity"] == 0, frame
        finally:
            browser.close()


def test_duplicate_status_reasserts_visibility_without_restarting_entry(e2e_base_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = open_overlay(browser, e2e_base_url)
            result = page.evaluate(r"""async () => {
              const state = window.__overlayE2e;
              state.emit("python_output", '{"status":"listening"}');
              const entry = document.querySelector("#w").getAnimations()
                .find(animation => animation.animationName === "widget-enter");
              entry.pause(); entry.currentTime = 100;
              state.visible = false;
              state.emit("python_output", '{"status":"listening"}');
              await Promise.resolve();
              const current = document.querySelector("#w").getAnimations()
                .find(animation => animation.animationName === "widget-enter");
              return {same: current === entry, time: current.currentTime,
                visible: state.visible,
                sounds: state.calls.filter(call => call.command === "sound").length};
            }""")
            assert result == {"same": True, "time": 100, "visible": True, "sounds": 1}
        finally:
            browser.close()


def test_rapid_overlay_restart_ends_visible_and_recording(e2e_base_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = open_overlay(browser, e2e_base_url)
            result = page.evaluate(r"""async () => {
              const state = window.__overlayE2e;
              for (const status of ["listening", "processing", "result", "listening"]) {
                state.emit("python_output", JSON.stringify({status}));
              }
              await new Promise(resolve => setTimeout(resolve, 0));
              return {visible: state.visible,
                recording: document.querySelector("#w").classList.contains("rec"),
                sounds: state.calls.filter(call => call.command === "sound").length};
            }""")
            assert result == {"visible": True, "recording": True, "sounds": 3}
        finally:
            browser.close()
