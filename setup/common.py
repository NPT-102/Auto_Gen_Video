"""Standard-library-only helpers: usable before the project venv exists."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command, cwd=ROOT, *, env=None) -> None:
    # Do not print arguments: some installer calls contain credentials.
    subprocess.run([str(arg) for arg in command], cwd=cwd, env=env, check=True)


def settings(root=ROOT) -> dict[str, str]:
    result = {}
    file = root / ".env"
    if file.exists():
        for line in file.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                result[key.strip()] = value.strip().strip('"').strip("'")
    result.update(os.environ)
    return result


def local_env(root=ROOT) -> dict[str, str]:
    """Keep installer caches/downloaded interpreters inside the project."""
    return {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
            "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", str(root / ".cache" / "uv")),
            "NPM_CONFIG_CACHE": os.environ.get("NPM_CONFIG_CACHE", str(root / ".cache" / "npm")),
            "UV_PYTHON_INSTALL_DIR": os.environ.get("UV_PYTHON_INSTALL_DIR", str(root / ".cache" / "python"))}
