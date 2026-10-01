import io
import json
import queue
import struct
import sys
import threading
import wave
from pathlib import Path
from unittest.mock import patch

import httpx
import numpy as np
import pytest
from playwright.sync_api import expect, sync_playwright


REPO_ROOT = Path(__file__).resolve().parents[2]
SIDECAR_ROOT = REPO_ROOT / "src-tauri"
if str(SIDECAR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIDECAR_ROOT))

from whisper_engine import audio as audio_module
from whisper_engine import engine as engine_module
from whisper_engine import ipc as ipc_module
from whisper_engine import transcriber
from whisper_engine.constants import (
    BLOCK_SIZE,
    GROQ_MODEL,
    GROQ_MULTIPART_BOUNDARY,
    GROQ_TRANSCRIPTION_URL,
    SAMPLE_RATE,
)
from whisper_engine.engine import WhisperEngine


TAURI_MOCK = r"""
(() => {
  const settings = {
    hotkey: "XBUTTON2",
    secondaryHotkey: "",
    model: "parakeet-tdt-0.6b-v3-int8",
    autoPaste: true,
    keepClipboardResult: true,
    minimizeTray: true,
    selectedDevice: "default",
    selectedLanguage: "it",
    computeDevice: "cpu",
    holdToSpeak: false,
    groqApiKey: "fake-e2e-key",
    provider: "cloud",
    widgetMode: "always",
  };
  const stats = { total_words: 0, avg_wpm: 0, total_time: 0 };
  const eventListeners = Object.create(null);
  const history = [];
  const calls = [];

  window.__e2e = {
    calls,
    history,
    settings,
    stats,
    listeners: eventListeners,
    emit(name, payload) {
      for (const listener of [...(eventListeners[name] || [])]) listener({ payload });
    },
  };

  window.__TAURI__ = {
    core: {
      async invoke(command, args = {}) {
        calls.push({ command, args: JSON.parse(JSON.stringify(args || {})) });
        switch (command) {
          case "load_settings": return { ...settings };
          case "save_settings": Object.assign(settings, args.settings || {}); return null;
          case "get_stats": return { ...stats };
          case "update_stats":
            stats.total_words += args.words || 0;
            stats.avg_wpm = args.wpm || 0;
            stats.total_time += args.timeDelta || 0;
            return { ...stats };
          case "get_audio_devices": return [{ id: "default", name: "E2E Fake Microphone" }];
          case "get_history": return [...history];
          case "save_transcription": history.unshift({
            text: args.text,
            timestamp: args.timestamp,
            word_count: args.wordCount,
          }); return null;
          case "delete_history_entry": history.splice(args.index, 1); return true;
          case "clear_history": history.splice(0, history.length); return null;
          case "check_model_exists": return false;
          case "execute_paste":
            if (window.__e2e.failPaste) throw new Error("simulated paste failure");
            return null;
          case "stop_python":
          case "send_to_python": return await window.__tauriBridgeInvoke(command, args);
          default: return null;
        }
      },
    },
    event: {
      async listen(name, listener) {
        (eventListeners[name] ||= []).push(listener);
        return () => {
          eventListeners[name] = (eventListeners[name] || []).filter((item) => item !== listener);
        };
      },
    },
    app: { async getVersion() { return "1.6.2-e2e"; } },
  };

  let draining = false;
  const drainTimer = window.setInterval(async () => {
    if (draining) return;
    draining = true;
    try {
      const events = await window.__drainSidecarEvents();
      for (const event of events) {
        window.__e2e.emit("python_output", JSON.stringify(event));
      }
    } catch (_) {
      // The browser shell can start before the test has exposed its event bridge.
    } finally {
      draining = false;
    }
  }, 20);
  window.__e2e.stopEventPolling = () => window.clearInterval(drainTimer);
})();
"""


@pytest.fixture
def browser_page():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        yield page
        browser.close()


def configure_tauri_bridge(page, invoke_bridge, drain_events):
    page.expose_binding("__tauriBridgeInvoke", invoke_bridge)
    page.expose_binding("__drainSidecarEvents", drain_events)
    page.add_init_script(TAURI_MOCK)


def open_app(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    page.wait_for_function("window.__e2e && window.__e2e.listeners.hotkey_pressed")


def test_cloud_ui_only_exposes_turbo_and_automatic_gain(browser_page, e2e_base_url):
    configure_tauri_bridge(browser_page, lambda _source, _command, _args: None, lambda _source: [])
    open_app(browser_page, e2e_base_url)

    browser_page.get_by_role("tab", name="Motore IA").click()
    expect(browser_page.get_by_role("heading", name="Whisper Large V3 Turbo")).to_be_visible()
    assert browser_page.locator("#groq-model").count() == 0
    assert browser_page.get_by_text("Whisper Large V3", exact=True).count() == 0
    assert browser_page.get_by_text("GPT", exact=False).count() == 0

    browser_page.get_by_role("tab", name="Sistema").click()
    expect(browser_page.get_by_text("Livello microfono automatico", exact=True)).to_be_visible()
    assert browser_page.locator('input[type="range"]').count() == 0


def test_paste_failure_keeps_history_and_shows_recovery_hint(browser_page, e2e_base_url):
    configure_tauri_bridge(browser_page, lambda _source, _command, _args: None, lambda _source: [])
    open_app(browser_page, e2e_base_url)
    browser_page.evaluate(
        """
        window.__e2e.failPaste = true;
        window.__e2e.emit("python_output", JSON.stringify({
          status: "result",
          text: "testo da recuperare",
          duration: 2,
          provider: "cloud",
        }));
        """
    )

    browser_page.wait_for_function(
        "window.__e2e.history.some((entry) => entry.text === 'testo da recuperare')"
    )
    expect(
        browser_page.get_by_text(
            "Incolla automatico non riuscito. Controlla Cronologia e copia il testo se è presente.",
            exact=True,
        )
    ).to_be_visible()


def test_sidecar_status_sync_is_not_gated_by_audio_probe(browser_page, e2e_base_url):
    configure_tauri_bridge(browser_page, lambda _source, _command, _args: None, lambda _source: [])
    browser_page.add_init_script(
        """
        (() => {
          const invoke = window.__TAURI__.core.invoke;
          window.__TAURI__.core.invoke = (command, args = {}) =>
            command === "get_audio_devices"
              ? new Promise(() => {})
              : invoke(command, args);
        })();
        """
    )
    open_app(browser_page, e2e_base_url)

    browser_page.wait_for_function(
        """
        window.__e2e.calls.some((call) =>
          call.command === "send_to_python" &&
          JSON.parse(call.args.message).command === "get_status"
        )
        """,
        timeout=1000,
    )


def test_hotkey_to_groq_to_ui_round_trip(browser_page, e2e_base_url):
    event_queue = queue.SimpleQueue()
    sidecar_commands = []
    audio_started = threading.Event()
    groq_request_seen = threading.Event()
    captured = {}
    events_seen = []

    engine = WhisperEngine()
    engine.provider = "cloud"
    engine.groq_api_key = "fake-e2e-key"
    engine.models_dir = None

    def log_event(event):
        events_seen.append(event)
        event_queue.put(event)

    engine.log = log_event
    engine.prepare_transcription_worker()

    sample_index = np.arange(BLOCK_SIZE * 3, dtype=np.float32)
    speech = (0.01 * np.sin(2 * np.pi * 220 * sample_index / SAMPLE_RATE)).astype(np.float32)
    blocks = [
        np.zeros((BLOCK_SIZE, 1), dtype=np.float32),
        np.zeros((BLOCK_SIZE, 1), dtype=np.float32),
        np.zeros((BLOCK_SIZE, 1), dtype=np.float32),
        speech[:BLOCK_SIZE, None],
        speech[BLOCK_SIZE : BLOCK_SIZE * 2, None],
        speech[BLOCK_SIZE * 2 :, None],
    ]
    raw_speech_levels = {
        audio_module.calculate_volume(block[:, 0]) for block in blocks[3:]
    }
    raw_peak = float(np.max(np.abs(speech)))

    class FakeInputStream:
        def __init__(self, **kwargs):
            self.callback = kwargs["callback"]

        def __enter__(self):
            for block in blocks:
                self.callback(block, BLOCK_SIZE, None, None)
            audio_started.set()
            return self

        def __exit__(self, *_args):
            return False

    def groq_handler(request):
        captured["request"] = request
        groq_request_seen.set()
        return httpx.Response(200, text="trascrizione e2e completata", request=request)

    client = httpx.Client(
        transport=httpx.MockTransport(groq_handler),
        headers={
            "Authorization": "Bearer fake-e2e-key",
            "Content-Type": f"multipart/form-data; boundary={GROQ_MULTIPART_BOUNDARY}",
        },
    )

    def invoke_bridge(_source, command, args):
        if command == "send_to_python":
            message = json.loads(args["message"])
            sidecar_commands.append(message)
            return ipc_module.handle_command(message.get("command"), message, engine)
        if command == "stop_python":
            sidecar_commands.append({"command": "stop"})
            return ipc_module.handle_command("stop", {}, engine)
        return None

    def drain_events(_source):
        drained = []
        while True:
            try:
                drained.append(event_queue.get_nowait())
            except queue.Empty:
                return drained

    transcriber.close_groq_client()
    configure_tauri_bridge(browser_page, invoke_bridge, drain_events)

    try:
        with (
            patch.object(engine_module.sd, "InputStream", FakeInputStream),
            patch.object(audio_module, "get_pre_roll", return_value=None),
            patch.object(transcriber, "create_groq_client", return_value=client),
        ):
            open_app(browser_page, e2e_base_url)
            expect(browser_page.get_by_text("Pronto", exact=True)).to_be_visible(timeout=5000)

            browser_page.evaluate("window.__e2e.emit('hotkey_pressed')")
            browser_page.wait_for_function(
                "window.__e2e.calls.some((call) => call.command === 'send_to_python' && "
                "JSON.parse(call.args.message).command === 'transcribe')"
            )
            assert audio_started.wait(timeout=2), "the mocked microphone did not start"
            expect(browser_page.get_by_text("Registrazione in corso", exact=True)).to_be_visible()

            browser_page.evaluate("window.__e2e.emit('hotkey_pressed')")
            browser_page.wait_for_function(
                "window.__e2e.calls.some((call) => call.command === 'stop_python')"
            )
            browser_page.wait_for_function(
                "window.__e2e.history.some((entry) => entry.text === 'trascrizione e2e completata')",
                timeout=5000,
            )
            assert groq_request_seen.wait(timeout=2), "the mocked Groq endpoint was not called"
            expect(browser_page.get_by_text("Cloud", exact=True)).to_be_visible()
            expect(browser_page.get_by_text("Pronto", exact=True)).to_be_visible()

        request = captured["request"]
        assert str(request.url) == GROQ_TRANSCRIPTION_URL
        assert b"whisper-large-v3-turbo\r\n" in request.content
        assert b"whisper-large-v3\r\n" not in request.content

        wav_start = request.content.index(b"RIFF")
        data_size = struct.unpack_from("<I", request.content, wav_start + 40)[0]
        wav_payload = request.content[wav_start : wav_start + 44 + data_size]
        with wave.open(io.BytesIO(wav_payload), "rb") as wav:
            amplified = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
        _assert_amplified_without_clipping(amplified, raw_peak)

        assert any(
            event.get("status") == "volume" and event.get("value") in raw_speech_levels
            for event in events_seen
        ), "the widget meter event did not retain the raw microphone level"
        assert any(command.get("command") == "transcribe" for command in sidecar_commands)
        browser_calls = browser_page.evaluate("window.__e2e.calls")
        assert any(call["command"] == "execute_paste" for call in browser_calls)
        assert any(call["command"] == "save_transcription" for call in browser_calls)

        browser_page.get_by_role("tab", name="Cronologia").click()
        history_entry = browser_page.locator("#history-list [role='listitem']").first
        delete_button = history_entry.get_by_role("button").nth(1)
        delete_button.click()
        expect(delete_button).to_have_text("Conferma eliminazione")
        delete_button.click()
        browser_page.wait_for_function("window.__e2e.history.length === 0")
        expect(browser_page.get_by_text("Le prossime trascrizioni appariranno qui.", exact=True)).to_be_visible()
        delete_calls = browser_page.evaluate("window.__e2e.calls")
        assert any(call["command"] == "delete_history_entry" for call in delete_calls)

        # The Sistema tab toggle must round-trip through save_settings so the
        # Rust side knows whether to restore the previous clipboard content.
        browser_page.get_by_role("tab", name="Sistema").click()
        checkbox = browser_page.locator("#keep-clipboard-result")
        expect(checkbox).to_be_checked()
        # The checkbox is visually hidden behind the custom switch, so drive it
        # the way a user does: clicking the label that wraps the control.
        browser_page.locator("label[for='keep-clipboard-result']").click()
        browser_page.wait_for_function(
            "window.__e2e.settings.keepClipboardResult === false"
        )
        browser_page.locator("label[for='keep-clipboard-result']").click()
        browser_page.wait_for_function("window.__e2e.settings.keepClipboardResult === true")
    finally:
        if not browser_page.is_closed():
            browser_page.evaluate("window.__e2e.stopEventPolling()")
        engine.close_transcription_worker()
        transcriber.close_groq_client()

    assert GROQ_MODEL == "whisper-large-v3-turbo"


def _assert_amplified_without_clipping(samples, raw_peak):
    output_peak = float(np.max(np.abs(samples))) / 32767.0
    assert output_peak > raw_peak * 2
    assert output_peak <= 0.981
