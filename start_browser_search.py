"""Start the isolated headless MCP process used for background Google search."""
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path


def running():
    try:
        with socket.create_connection(("127.0.0.1", 8932), timeout=.5):
            return True
    except OSError:
        return False


def start():
    if running():
        return
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        raise RuntimeError("Background search requires Node.js/npm and Google Chrome.")
    env = dict(os.environ)
    env.pop("PLAYWRIGHT_MCP_EXTENSION_TOKEN", None)
    process = subprocess.Popen([npm, "exec", "--yes", "--package=@playwright/mcp@0.0.83", "--",
        "playwright-mcp", "--headless", "--isolated", "--browser", "chrome", "--port", "8932",
        "--host", "127.0.0.1", "--timeout-navigation", "15000"], cwd=Path.home(), env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for _ in range(100):
        if running():
            return
        if process.poll() is not None:
            raise RuntimeError("Background Playwright search did not start.")
        time.sleep(.1)
    raise RuntimeError("Background Playwright search startup timed out.")


if __name__ == "__main__":
    start()
    print("Background Playwright search: ready (no visible browser window)")
