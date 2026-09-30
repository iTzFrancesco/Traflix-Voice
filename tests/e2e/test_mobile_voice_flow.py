from playwright.sync_api import expect, sync_playwright


TAURI_MOCK = r"""
(() => {
  const calls = [];
  window.__mobileE2e = { calls };
  window.__TAURI__ = {
    core: {
      async invoke(command, args = {}) {
        calls.push({ command, args });
        if (command === "load_settings") {
          return {
            hotkey: "XBUTTON2", secondaryHotkey: "", model: "parakeet-tdt-0.6b-v3-int8",
            autoPaste: true, minimizeTray: true, selectedDevice: "default",
            selectedLanguage: "it", computeDevice: "cpu", holdToSpeak: false,
            groqApiKey: "fake-mobile-key", provider: "cloud", widgetMode: "always",
          };
        }
        if (command === "get_stats") {
          return { total_words: 0, avg_wpm: 0, total_time: 0 };
        }
        if (command === "get_history") return [];
        if (command === "get_groq_usage") return new Promise(() => {});
        if (command === "plugin:voice-runtime|getRuntimeState") return new Promise(() => {});
        return null;
      },
    },
    app: { async getVersion() { return "0.1.17"; } },
  };
})();
"""


def test_mobile_dashboard_does_not_wait_for_optional_bridge(e2e_base_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 420, "height": 860},
            user_agent=(
                "Mozilla/5.0 (Linux; Android 14; Pixel 8) "
                "AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36"
            ),
        )
        page.add_init_script(TAURI_MOCK)
        page.goto(e2e_base_url, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")

        expect(
            page.get_by_role("heading", name="Panoramica", exact=True)
        ).to_be_visible(timeout=1500)
        page.wait_for_timeout(2200)
        runtime_calls = page.evaluate(
            "window.__mobileE2e.calls.filter("
            "(call) => call.command === 'plugin:voice-runtime|getRuntimeState'"
            ").length"
        )
        assert runtime_calls <= 2
        browser.close()
