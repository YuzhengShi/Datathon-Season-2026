"""Verify the documented CLI and real HTTP routes within one local process environment."""

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx


def main():
    backend = Path(__file__).resolve().parents[1]
    env = {**os.environ, "DATA_MODE": "demo", "LLM_ENABLED": "false"}
    base = "http://127.0.0.1:8127"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "navigator.cli",
            "serve",
            "--mode",
            "demo",
            "--host",
            "127.0.0.1",
            "--port",
            "8127",
        ],
        cwd=backend,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        with httpx.Client(base_url=base, timeout=1, trust_env=False) as client:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("CLI server did not start: " + process.stdout.read())
                try:
                    if client.get("/api/health").status_code == 200:
                        break
                except httpx.ConnectError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Local HTTP server did not become ready")
        subprocess.run(
            [sys.executable, str(backend / "scripts/smoke_test.py"), "--base-url", base],
            check=True,
            cwd=backend,
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
