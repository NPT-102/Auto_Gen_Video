#!/usr/bin/env python3
"""Start the local web app using factory's venv; Ctrl+C stops it."""
import argparse
import subprocess
import threading
import urllib.request
import webbrowser

from factory.config import PORT
from factory.pyrun import python_path, venv_python
from setup.common import ROOT, local_env


def open_when_ready(url: str, stopped: threading.Event) -> None:
    for _ in range(60):
        if stopped.wait(0.5):
            return
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=0.5) as response:
                if response.status == 200:
                    webbrowser.open(url)
                    return
        except OSError:
            pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Start Video Factory web UI")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser (headless/SSH)")
    args = parser.parse_args(argv)
    if not python_path(ROOT / ".venv").exists():
        parser.error("Factory .venv is missing. Run python3 cai-dat.py first.")
    url = f"http://127.0.0.1:{args.port}"
    print(f"Video Factory: {url} (Ctrl+C to stop)", flush=True)
    stopped = threading.Event()
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url, stopped), daemon=True).start()
    try:
        return subprocess.run([*venv_python(ROOT / ".venv"), "-m", "uvicorn", "factory.app:app",
                               "--host", "127.0.0.1", "--port", str(args.port)],
                              cwd=ROOT, env=local_env(ROOT)).returncode
    except KeyboardInterrupt:
        return 130
    finally:
        stopped.set()


if __name__ == "__main__":
    raise SystemExit(main())
