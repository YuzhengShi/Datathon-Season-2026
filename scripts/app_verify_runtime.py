"""Verify the documented CLI and real HTTP routes of the application layer in one local process environment.

Starts `python -m navigator.cli serve --mode demo` on a spare port, runs scripts/app_smoke_test.py against it, stops it.
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx


def free_port() -> int:
    """A port nothing listens on: a fixed one can belong to a server that is already running."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "DATA_MODE": "demo", "LLM_ENABLED": "false", "PYTHONUTF8": "1"}
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [sys.executable, "-m", "navigator.cli", "serve", "--mode", "demo", "--host", "127.0.0.1", "--port", str(port)],
        cwd=root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        with httpx.Client(base_url=base, timeout=1, trust_env=False) as client:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("CLI server did not start: " + process.stdout.read())
                try:
                    if client.get("/api/health").status_code == 200:
                        break
                except httpx.TransportError:
                    time.sleep(0.2)
            else:
                raise RuntimeError("Local HTTP server did not become ready")
        subprocess.run(
            [sys.executable, str(root / "scripts" / "app_smoke_test.py"), "--base-url", base],
            check=True,
            cwd=root,
            env=env,
        )
        print("CLI startup and local HTTP smoke verified.")
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


if __name__ == "__main__":
    main()
