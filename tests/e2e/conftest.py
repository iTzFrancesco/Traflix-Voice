import os
import shutil
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest


@pytest.fixture(scope="session")
def e2e_base_url():
    configured_url = os.environ.get("TRAFIX_E2E_BASE_URL")
    if configured_url:
        yield configured_url.rstrip("/")
        return

    repo_root = Path(__file__).resolve().parents[2]
    vite_cli = repo_root / "node_modules" / "vite" / "bin" / "vite.js"
    node = shutil.which("node")
    if not node or not vite_cli.is_file():
        pytest.fail("Install Node dependencies with `npm install` before running E2E tests.")

    port = int(os.environ.get("TRAFIX_E2E_PORT", "1420"))
    base_url = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [node, str(vite_cli), "--host", "127.0.0.1", "--port", str(port), "--strictPort"],
        cwd=repo_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            pytest.fail(f"Vite exited before becoming ready (exit code {process.returncode}).")
        try:
            with urlopen(base_url, timeout=1):
                break
        except (OSError, URLError):
            time.sleep(0.1)
    else:
        process.terminate()
        pytest.fail(f"Vite did not become ready at {base_url} within 30 seconds.")

    try:
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
