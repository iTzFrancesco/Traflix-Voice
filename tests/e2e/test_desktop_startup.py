import json

from playwright.sync_api import expect, sync_playwright


TAURI_MOCK = r"""
(() => {
  const calls = [];
  const listeners = {};
  window.__startupE2e = { calls };
  window.__TAURI__ = {
    core: {
      async invoke(command, args = {}) {
        calls.push({ command, args });
        if (command === "load_settings") {
          return {
            hotkey: "XBUTTON2", secondaryHotkey: "", model: "parakeet-tdt-0.6b-v3-int8",
            autoPaste: true, minimizeTray: true, selectedDevice: "default",
            selectedLanguage: "it", computeDevice: "cpu", holdToSpeak: false,
            groqApiKey: "fake-key", provider: "cloud", widgetMode: "always",
          };
        }
        if (command === "get_stats") return { total_words: 0, avg_wpm: 0, total_time: 0 };
        if (command === "get_audio_devices") return [];
        if (command === "get_groq_usage") {
          return { date: "", audio_seconds: 0, audio_seconds_hourly: 0, hourly_reset: "" };
        }
        if (command === "send_to_python") {
          return window.__statusBridge(args);
        }
        return null;
      },
    },
    event: {
      async listen(name, listener) {
        (listeners[name] ||= []).push(listener);
        return () => {};
      },
    },
    app: { async getVersion() { return "1.6.4"; } },
  };
})();
"""


def open_desktop(page, base_url, mock=TAURI_MOCK):
    page.add_init_script(mock)
    page.goto(base_url, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("Panoramica", exact=True)).to_be_visible()


def test_desktop_status_sync_retries_once_after_bridge_failure(e2e_base_url):
    attempts = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        def status_bridge(_source, args):
            message = json.loads(args["message"])
            if message.get("command") != "get_status":
                return None
            attempts.append(message)
            if len(attempts) == 1:
                raise RuntimeError("sidecar not ready")
            return None

        page.expose_binding("__statusBridge", status_bridge)
        open_desktop(page, e2e_base_url)
        page.wait_for_function(
            """
            window.__startupE2e.calls.filter((call) =>
              call.command === "send_to_python" &&
              JSON.parse(call.args.message).command === "get_status"
            ).length === 2
            """,
            timeout=1500,
        )
        assert len(attempts) == 2
        browser.close()


def test_desktop_status_sync_is_not_gated_by_audio_probe(e2e_base_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.expose_binding("__statusBridge", lambda _source, _args: None)
        open_desktop(
            page,
            e2e_base_url,
            TAURI_MOCK.replace(
                'if (command === "get_audio_devices") return [];',
                'if (command === "get_audio_devices") return new Promise(() => {});',
            ),
        )
        page.wait_for_function(
            """
            window.__startupE2e.calls.some((call) =>
              call.command === "send_to_python" &&
              JSON.parse(call.args.message).command === "get_status"
            )
            """,
            timeout=1000,
        )
        browser.close()
