# Desktop end-to-end tests

The suite drives the React desktop UI in Chromium, forwards Tauri calls to the
Python sidecar command handler, captures deterministic microphone blocks, and
uses an HTTPX mock instead of making a real Groq request. It covers the full
hotkey → capture → automatic gain → Turbo multipart → result → UI paste/history
path without recording user audio or using API credentials.

Install the optional browser test dependencies and Chromium once:

```powershell
py -3 -m pip install -r src-tauri/requirements.txt -r tests/e2e/requirements.txt
py -3 -m playwright install chromium
```

Then run the complete Python and browser suite from the repository root:

```powershell
npm run test:e2e
```

The browser suite starts Vite on `127.0.0.1:1420` by default. Set
`TRAFIX_E2E_PORT` to use a different free port, or set
`TRAFIX_E2E_BASE_URL` to use a server that is already running.
