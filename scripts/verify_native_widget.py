#!/usr/bin/env python3
"""Verify real Tauri window restoration in an isolated development instance."""

import argparse
import json

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cdp-url", default="http://127.0.0.1:49333")
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(args.cdp_url)
        pages = [page for context in browser.contexts for page in context.pages]
        main_page = next(page for page in pages if page.evaluate(
            "window.__TAURI__?.window?.getCurrentWindow().label") == "main")
        overlay = next(page for page in pages if page.evaluate(
            "window.__TAURI__?.window?.getCurrentWindow().label") == "overlay")
        identifier = main_page.evaluate("window.__TAURI__.app.getIdentifier()")
        if identifier != "it.traflix.voice.verification":
            raise RuntimeError("Use the isolated it.traflix.voice.verification development app")
        main_page.evaluate("""async () => {
          const settings = await window.__TAURI__.core.invoke('load_settings');
          settings.widgetMode = 'recording';
          settings.hotkey = ''; settings.secondaryHotkey = '';
          settings.autoPaste = false;
          await window.__TAURI__.core.invoke('save_settings', {settings});
          await window.__TAURI__.window.getCurrentWindow().close();
        }""")
        overlay.wait_for_function("async () => !(await window.__TAURI__.window.getCurrentWindow().isVisible())")
        results = []
        for status in ("listening", "processing"):
            overlay.evaluate("status => window.__TAURI__.event.emit('python_output', JSON.stringify({status}))", status)
            overlay.wait_for_function("async () => await window.__TAURI__.window.getCurrentWindow().isVisible()")
            overlay.locator("#w").press("Enter")
            main_page.wait_for_function("async () => await window.__TAURI__.window.getCurrentWindow().isVisible()")
            overlay.wait_for_function("async () => !(await window.__TAURI__.window.getCurrentWindow().isVisible())")
            main_page.evaluate("window.__TAURI__.window.getCurrentWindow().close()")
            overlay.wait_for_function("async () => await window.__TAURI__.window.getCurrentWindow().isVisible()")
            overlay.wait_for_function("Number(getComputedStyle(document.querySelector('#w')).opacity) === 1")
            assert overlay.locator("#w").evaluate("widget => getComputedStyle(widget).pointerEvents") != "none"
            overlay.evaluate("window.__TAURI__.event.emit('python_output', '{\"status\":\"ready\"}')")
            overlay.wait_for_function("async () => !(await window.__TAURI__.window.getCurrentWindow().isVisible())")
            results.append({"status": status, "restored": True, "hidden_after_ready": True})
        print(json.dumps({"identifier": identifier, "results": results}))


if __name__ == "__main__":
    main()
