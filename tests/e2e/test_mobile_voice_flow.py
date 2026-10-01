from playwright.sync_api import expect, sync_playwright


TAURI_MOCK = r"""
(() => {
  const calls = [];
  const history = [
    { text: "trascrizione recente", timestamp: "01/10/2026, 12:00", word_count: 2 },
    { text: "trascrizione precedente", timestamp: "01/10/2026, 11:00", word_count: 2 },
  ];
  const stats = { total_words: 4, avg_wpm: 60, total_time: 0.1 };
  window.__mobileE2e = { calls, history, stats };
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
          return { ...stats };
        }
        if (command === "get_history") return [...history];
        if (command === "plugin:voice-runtime|deleteHistoryEntry") {
          const entry = history[args.index];
          const matches = entry && entry.text === args.text &&
            entry.timestamp === args.timestamp && entry.word_count === args.wordCount;
          if (!matches) return { deleted: false };
          history.splice(args.index, 1);
          return { deleted: true };
        }
        if (command === "plugin:voice-runtime|clearHistoryAndStats") {
          history.splice(0, history.length);
          Object.assign(stats, { total_words: 0, avg_wpm: 0, total_time: 0 });
          return null;
        }
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


def test_mobile_history_mutations_use_native_storage_bridge(e2e_base_url):
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

        page.get_by_role("button", name="Cronologia").click()
        expect(page.get_by_text("trascrizione recente", exact=True)).to_be_visible()
        page.get_by_role(
            "button", name="Elimina trascrizione del 01/10/2026, 12:00"
        ).click()
        page.get_by_role(
            "button", name="Conferma eliminazione trascrizione del 01/10/2026, 12:00"
        ).click()
        page.wait_for_function(
            "window.__mobileE2e.history.length === 1 && "
            "window.__mobileE2e.history[0].text === 'trascrizione precedente'"
        )
        delete_call = page.evaluate(
            "window.__mobileE2e.calls.find((call) => "
            "call.command === 'plugin:voice-runtime|deleteHistoryEntry')"
        )
        assert delete_call["args"] == {
            "index": 0,
            "text": "trascrizione recente",
            "timestamp": "01/10/2026, 12:00",
            "wordCount": 2,
        }

        page.get_by_role("button", name="Cancella", exact=True).click()
        page.get_by_role("button", name="Conferma", exact=True).click()
        page.wait_for_function("window.__mobileE2e.history.length === 0")
        expect(page.get_by_text("Nessuna trascrizione ancora", exact=True)).to_be_visible()
        assert page.evaluate(
            "window.__mobileE2e.calls.some((call) => "
            "call.command === 'plugin:voice-runtime|clearHistoryAndStats')"
        )
        assert page.evaluate("window.__mobileE2e.stats.total_words") == 0
        browser.close()
