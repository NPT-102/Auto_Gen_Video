"""Repeatable native setup: same pinned engines as the former PowerShell installer."""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from factory.config import _chrome, resolve_path
from factory.pyrun import npm_command, python_path, venv_python
from .common import ROOT, local_env, run, settings

REPOS = {
    "mpt": ("MoneyPrinterTurbo", "https://github.com/harry0703/MoneyPrinterTurbo.git",
            "ad5496f1b729d1d7e361dd972015d26c08b0e052"),
    "aiauto": ("ai-auto-generate-video", "https://github.com/huytranvan2010/AI-auto-generate-video.git",
               "66507ab98c8ed81bcfdbc1cc31cc634d068bc127"),
    "pixelle": ("pixelle-video", "https://github.com/ATH-MaaS/Pixelle-Video.git",
                "848b054e4fae40dabc62ec58e960b573e83793ac"),
}
ENGINES = ("hyperframes", "remotion", "whiteboard", "broll", "mpt", "aiauto", "pixelle")


def check_tools() -> bool:
    ok = True
    for tool in ("git", "uv", "node", "npm", "ffmpeg", "ffprobe"):
        found = shutil.which(tool)
        print(f"[{'ok' if found else '--'}] {tool}: {found or 'missing'}")
        ok = ok and bool(found)
    if shutil.which("node"):
        version = subprocess.check_output(["node", "--version"], text=True).strip()
        if int(version.lstrip("v").split(".")[0]) < 22:
            print("Node.js >= 22 is required.")
            ok = False
    browser = _chrome()
    print(f"[{'ok' if browser.exists() else '--'}] Chrome/Chromium: {browser}")
    if not browser.exists():
        print("Install Chrome/Chromium or set CHROME_PATH in .env.")
        ok = False
    return ok


def ensure_env() -> None:
    target = ROOT / ".env"
    if not target.exists():
        shutil.copy2(ROOT / ".env.example", target)
        print("Created .env. Enter GEMINI_API_KEY and PIXABAY_API_KEY or PEXELS_API_KEY.")


def ensure_repo(directory: Path, url: str, revision: str) -> None:
    if (directory / ".git").exists():
        print(f"Keeping existing checkout: {directory}")
        return
    if directory.exists():
        raise RuntimeError(f"{directory} already exists but is not a Git checkout; move it before retrying.")
    directory.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "clone", "--filter=blob:none", "--no-checkout", url, directory])
    run(["git", "-c", "advice.detachedHead=false", "-C", directory, "checkout", "--quiet", revision])


def install_node(directory: Path) -> None:
    # Re-run npm ci: an interrupted installation may already have node_modules.
    run([npm_command(), "ci", "--no-audit", "--no-fund"], cwd=directory, env=local_env(ROOT))


def sync_engine_env(directory: Path, name: str, python: str, environment: dict) -> None:
    command = ["uv", "sync", "--frozen", "--python", python]
    if name == "pixelle":
        command.append("--no-install-project")
    try:
        run(command, cwd=directory, env=environment)
    except subprocess.CalledProcessError:
        if name != "pixelle":
            raise
        # Preserve the Windows SAC workaround: build moviepy inside the venv
        # instead of executing uv's unsigned temporary build interpreter.
        print("Retrying Pixelle: build moviepy inside its venv.")
        run([*command, "--no-build-isolation-package", "moviepy"], cwd=directory, env=environment)


def _toml_setting(text: str, section: str, key: str, value) -> str:
    """Update one table without discarding comments or unrelated user settings."""
    header = re.search(rf"(?m)^\[{re.escape(section)}\]\s*$", text)
    line = f"{key} = {json.dumps(value, ensure_ascii=False)}"
    if not header:
        return text.rstrip() + f"\n\n[{section}]\n{line}\n"
    end = re.search(r"(?m)^\[", text[header.end():])
    stop = header.end() + end.start() if end else len(text)
    body = text[header.end():stop]
    pattern = rf"(?m)^{re.escape(key)}\s*=[^\r\n]*"
    if re.search(pattern, body):
        body = re.sub(pattern, lambda _: line, body, count=1)
    else:
        body = body.rstrip() + "\n" + line + "\n"
    return text[:header.end()] + body + text[stop:]


def sync_mpt_config(directory: Path, values: dict[str, str]) -> None:
    target = directory / "config.toml"
    source = target if target.exists() else directory / "config.example.toml"
    text = source.read_text(encoding="utf-8-sig")
    if not target.exists():
        for key, value in {"llm_provider": "gemini", "gemini_model_name": "gemini-flash-latest",
                           "edge_tts_timeout": 120}.items():
            text = _toml_setting(text, "app", key, value)
        for key, value in {"language": "vi", "font_name": "BeVietnamPro-Bold.ttf",
                           "voice_name": "vi-VN-HoaiMyNeural-Female"}.items():
            text = _toml_setting(text, "ui", key, value)
    for env_key, key, array in (("GEMINI_API_KEY", "gemini_api_key", False),
                                ("PEXELS_API_KEY", "pexels_api_keys", True)):
        if values.get(env_key):
            value = values[env_key]
            text = _toml_setting(text, "app", key, [value] if array else value)
    tomllib.loads(text)  # Validate before replacing a user's config.
    temporary = target.with_suffix(".toml.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(target)
    print("MoneyPrinterTurbo config synchronized (key values are not printed).")


def show_status(selected=ENGINES) -> int:
    if not python_path(ROOT / ".venv").exists():
        print("Factory .venv is missing. Run python3 cai-dat.py first.")
        return 1
    command = [*venv_python(ROOT / ".venv"), "-m", "factory.status", "--engines", *selected]
    return subprocess.run(command, cwd=ROOT, env=local_env(ROOT)).returncode


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Install Video Factory on Linux or Windows")
    parser.add_argument("--check", "-KiemTra", action="store_true", help="Only inspect tools and engine readiness")
    parser.add_argument("--engines", nargs="+", choices=ENGINES, default=list(ENGINES),
                        help="Engines to install; default: all six")
    parser.add_argument("--python", default="3.12", help="Python version/interpreter for factory and engine venvs")
    parser.add_argument("--with-whisper", action="store_true", help="Compatibility flag; Whisper is included in factory dependencies")
    args = parser.parse_args(argv)
    try:
        tools_ok = check_tools()
        if args.check:
            status = show_status(args.engines)
            return status if tools_ok else 1
        if not tools_ok:
            print("Install missing system tools first; see the Linux section of README.md.")
            return 1
        ensure_env()
        environment = local_env(ROOT)
        run(["uv", "sync", "--frozen", "--python", args.python], cwd=ROOT, env=environment)
        install_node(ROOT / "tools" / "elk")
        for name in ("hyperframes", "remotion", "whiteboard"):
            if name in args.engines:
                project = {"hyperframes": "hyperframes-academic", "remotion": "remotion-academic",
                           "whiteboard": "remotion-whiteboard"}[name]
                install_node(ROOT / "engines" / project)
        if "whiteboard" in args.engines and not (ROOT.parent / "whiteboard-lab" / "lab" / "module.py").exists():
            # Whiteboard Lab bundled in engines/whiteboard-lab (numpy, Pillow, OpenCV) unless the original Lab sits
            # beside the repository (factory/config.py picks the same one)
            run(["uv", "sync", "--frozen", "--python", args.python], cwd=ROOT / "engines" / "whiteboard-lab",
                env=environment)
        values = settings(ROOT)
        for name in args.engines:
            if name not in REPOS:
                continue
            folder, url, revision = REPOS[name]
            directory = ROOT / "engines" / folder
            if name == "mpt":
                beside = ROOT.parent / folder
                if values.get("MPT_DIR"):
                    directory = resolve_path(values["MPT_DIR"])
                elif not directory.exists() and (beside / "cli.py").exists():
                    directory = beside
            ensure_repo(directory, url, revision)
            if name == "aiauto":
                install_node(directory)
            else:
                sync_engine_env(directory, name, args.python, environment)
                if name == "mpt":
                    sync_mpt_config(directory, values)
                else:
                    run([*venv_python(directory / ".venv"), "-m", "playwright", "install", "--only-shell", "chromium"],
                        cwd=directory, env=environment)
        for key in ("GEMINI_API_KEY",):
            if not values.get(key):
                print(f"{key} is not set; edit .env before using that service.")
        if not (values.get("PIXABAY_API_KEY") or values.get("PEXELS_API_KEY")):
            print("Enter PIXABAY_API_KEY or PEXELS_API_KEY in .env to use stock media.")
        result = show_status(args.engines)
        print("Start the web app: python3 chay-web.py")
        return result
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        # CalledProcessError.args may include sensitive config arguments; print only the exit code.
        print(f"Setup failed: command exited {exc.returncode}" if isinstance(exc, subprocess.CalledProcessError)
              else f"Setup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
