"""Capture the README hero screenshot of the desktop window.

Renders the Vite app in headless Chromium with the same Tauri mock used by
the e2e suite, then saves ``docs/assets/readme/traflix-voice-desktop.webp``.
Regenerate after visible UI changes so the GitHub hero stays current::

    python scripts/capture_readme_screenshots.py
"""
import io
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src-tauri"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "e2e"))

from test_desktop_voice_flow import TAURI_MOCK  # noqa: E402

PORT = 1431
BASE_URL = f"http://127.0.0.1:{PORT}"
OUT_PATH = REPO_ROOT / "docs" / "assets" / "readme" / "traflix-voice-desktop.webp"

# Same shape as the e2e mock, but with release-like data so the hero shows
# the current Home tab instead of an empty state.
MOCK = (
    TAURI_MOCK.replace('"1.6.2-e2e"', '"1.6.9"')
    .replace('cloudVocabulary: "Traflix Voice, Groq Cloud"',
             'cloudVocabulary: "Traflix Streaming\\nTraflix Voice\\nsubagent"')
    .replace("const stats = { total_words: 0, avg_wpm: 0, total_time: 0 };",
             "const stats = { total_words: 12480, avg_wpm: 108, total_time: 96 };")
)


def wait_for_vite(process):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Vite exited early (code {process.returncode}).")
        try:
            with urlopen(BASE_URL, timeout=1):
                return
        except (OSError, URLError):
            time.sleep(0.1)
    process.terminate()
    raise RuntimeError(f"Vite did not become ready at {BASE_URL}.")


def main():
    from playwright.sync_api import sync_playwright

    dist = REPO_ROOT / "dist"
    if not dist.is_dir():
        raise RuntimeError("Run `npm run build` first so the hero matches the release UI.")

    preview_cli = REPO_ROOT / "node_modules" / "vite" / "bin" / "vite.js"
    node = shutil.which("node")
    if not node or not preview_cli.is_file():
        raise RuntimeError("Install Node dependencies with `npm install` first.")

    process = subprocess.Popen(
        [node, str(preview_cli), "preview", "--host", "127.0.0.1",
         "--port", str(PORT), "--strictPort"],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    try:
        wait_for_vite(process)
        # Persistent so the status badge reads "Pronto" no matter when the
        # app mounts its event listener.
        ready = [{"status": "ready", "message": "Motore Whisper pronto."}]

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 450, "height": 650}, device_scale_factor=2)

            def invoke_bridge(source, command, args):
                return None

            def drain_events(source):
                return ready

            page.expose_binding("__tauriBridgeInvoke", invoke_bridge)
            page.expose_binding("__drainSidecarEvents", drain_events)
            page.add_init_script(MOCK)
            page.goto(BASE_URL, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle")
            page.wait_for_function("window.__e2e && window.__e2e.listeners.hotkey_pressed")
            page.wait_for_function(
                "document.body.textContent.includes('Pronto')"
            )
            page.wait_for_timeout(400)
            png = page.screenshot()
            if not page.is_closed():
                page.evaluate("window.__e2e?.stopEventPolling()")
                page.wait_for_timeout(50)
            browser.close()
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    from PIL import Image

    image = Image.open(io.BytesIO(png))
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT_PATH, "WEBP", quality=85, method=6)
    print(f"Saved {OUT_PATH} ({image.size[0]}x{image.size[1]})")


if __name__ == "__main__":
    main()
