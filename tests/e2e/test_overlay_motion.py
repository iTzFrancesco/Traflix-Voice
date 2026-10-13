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
    const transform = new DOMMatrix(getComputedStyle(document.querySelector("#w")).transform);
    const label = document.querySelector(".lbl");
    return {ms, left: widget.left, right: widget.right,
      scale: transform.a, offsetY: transform.f,
      labelWidth: label.getBoundingClientRect().width,
      labelOpacity: Number(getComputedStyle(label).opacity)};
  });
}
"""


def open_overlay(browser, base_url, device_scale_factor=1, widget_mode="recording"):
    page = browser.new_page(
        viewport={"width": 170, "height": 50},
        device_scale_factor=device_scale_factor,
    )
    page.add_init_script(TAURI_MOCK.replace('widgetMode: "recording"', f'widgetMode: "{widget_mode}"'))
    page.goto(f"{base_url}/overlay.html", wait_until="networkidle")
    if widget_mode == "recording":
        page.wait_for_function("window.__overlayE2e.calls.some(call => call.command === 'hide')")
    else:
        page.wait_for_function("window.__overlayE2e.listeners.has('python_output')")
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
                assert frame["labelWidth"] >= 0, frame
                assert 0 <= frame["labelOpacity"] <= 1, frame
            assert frames[-1]["labelWidth"] == 0, frames
            assert frames[-1]["labelOpacity"] == 0, frames
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


def test_overlay_entry_uses_small_motion_without_overshoot(e2e_base_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = open_overlay(browser, e2e_base_url)
            frames = page.evaluate(ENTRY_FRAMES)
            for frame in frames:
                assert 0.98 <= frame["scale"] <= 1.0001, frame
                assert -0.01 <= frame["offsetY"] <= 4, frame
            assert all(previous["offsetY"] >= current["offsetY"]
                       for previous, current in zip(frames, frames[1:]))
        finally:
            browser.close()


@pytest.mark.parametrize("show_dev_badge", [False, True])
def test_compact_processing_widget_keeps_the_status_label_visible(e2e_base_url, show_dev_badge):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = open_overlay(browser, e2e_base_url)
            if not show_dev_badge:
                page.locator(".dev-slot").evaluate("slot => slot.replaceChildren()")
            page.evaluate("window.__overlayE2e.emit('python_output', '{\"status\":\"processing\"}')")
            page.wait_for_function(r"""() => {
              const label = document.querySelector('.proc-label').getBoundingClientRect();
              const wrap = document.querySelector('.spw').getBoundingClientRect();
              return wrap.width > 50 && label.right <= wrap.right + 0.01;
            }""", timeout=3000)
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


def test_visible_idle_widget_morphs_into_audio_without_reappearing(e2e_base_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = open_overlay(browser, e2e_base_url, widget_mode="always")
            result = page.evaluate(r"""() => {
              const widget = document.querySelector('#w');
              const label = document.querySelector('.lbl');
              const wave = document.querySelector('.vw');
              const initialWidth = label.getBoundingClientRect().width;
              window.__overlayE2e.emit('python_output', '{"status":"listening"}');
              const animations = widget.getAnimations({subtree:true});
              animations.forEach(animation => animation.pause());
              const frames = [0, 60, 120, 220, 320, 480].map(ms => {
                animations.forEach(animation => animation.currentTime = ms);
                return {ms, labelWidth:label.getBoundingClientRect().width,
                  waveWidth:wave.getBoundingClientRect().width,
                  opacity:Number(getComputedStyle(widget).opacity)};
              });
              return {initialWidth, frames,
                entry:animations.some(animation => animation.animationName === 'widget-enter')};
            }""")
            assert not result["entry"], result
            assert all(frame["opacity"] == 1 for frame in result["frames"]), result
            middle, final = result["frames"][2], result["frames"][-1]
            assert 0 < middle["labelWidth"] < result["initialWidth"], result
            assert 0 < middle["waveWidth"] < final["waveWidth"], result
            assert final["labelWidth"] == 0 and final["waveWidth"] > 0, result
        finally:
            browser.close()


@pytest.mark.parametrize("status", ["ready", "listening", "processing"])
def test_hover_content_stays_inside_native_overlay_viewport(e2e_base_url, status):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = open_overlay(browser, e2e_base_url, widget_mode="always")
            page.evaluate("status => window.__overlayE2e.emit('python_output', JSON.stringify({status}))", status)
            page.locator('#w').hover()
            page.wait_for_timeout(550)
            overflow = page.evaluate(r"""() => [...document.querySelector('#w').children]
              .filter(element => {
                const style = getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return Number(style.opacity) > 0 && style.visibility !== 'hidden'
                  && rect.width > 0 && rect.height > 0;
              }).map(element => ({className:element.className, rect:element.getBoundingClientRect().toJSON()}))
              .filter(({rect}) => rect.left < 0 || rect.top < 0
                || rect.right > window.innerWidth || rect.bottom > window.innerHeight)""")
            assert not overflow, overflow
        finally:
            browser.close()


def test_reduced_motion_reaches_recording_layout_without_spatial_transition(e2e_base_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = open_overlay(browser, e2e_base_url, widget_mode="always")
            page.emulate_media(reduced_motion="reduce")
            result = page.evaluate(r"""async () => {
              window.__overlayE2e.emit('python_output', '{"status":"listening"}');
              await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
              return {labelWidth:document.querySelector('.lbl').getBoundingClientRect().width,
                waveWidth:document.querySelector('.vw').getBoundingClientRect().width,
                opacity:Number(getComputedStyle(document.querySelector('#w')).opacity)};
            }""")
            assert result["labelWidth"] == 0 and result["waveWidth"] > 0, result
            assert result["opacity"] == 1, result
        finally:
            browser.close()
