"""Optional native ComfyUI installation. CPU by default; no Windows archive needed."""

import argparse
import hashlib
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from factory.pyrun import python_path, venv_python
from .common import ROOT, local_env, run
from .install import ensure_repo

MODEL_NAME = "sdxl_lightning_4step.safetensors"
MODEL_SIZE = 6938040682
MODEL_SHA256 = "e0d996ee0013e79d9d3561f50fcafb9a17e3ff07b780358e3b66d67932c4d490"
MODEL_URL = "https://huggingface.co/ByteDance/SDXL-Lightning/resolve/main/" + MODEL_NAME


def verified(path: Path, size: int, digest: str) -> bool:
    if not path.exists() or path.stat().st_size != size:
        return False
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest().lower() == digest.lower()


def download_model(target: Path, url=MODEL_URL, size=MODEL_SIZE, digest=MODEL_SHA256) -> None:
    if verified(target, size, digest):
        print(f"Checkpoint already verified: {target.name}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    for attempt in range(3):
        offset = part.stat().st_size if part.exists() else 0
        if offset == size:
            break
        if offset > size:
            part.unlink()
            offset = 0
        request = urllib.request.Request(url, headers={"Range": f"bytes={offset}-"} if offset else {})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                resume = response.status == 206 and offset > 0
                if resume and not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                    raise RuntimeError("Model server returned an unexpected Content-Range.")
                with part.open("ab" if resume else "wb") as file:
                    shutil.copyfileobj(response, file, length=1024 * 1024)
            if part.stat().st_size == size:
                break
        except (OSError, urllib.error.URLError) as exc:
            print(f"Download interrupted ({type(exc).__name__}); retry {attempt + 1}/3.")
        if attempt < 2:
            time.sleep(1)
    if not verified(part, size, digest):
        raise RuntimeError("Checkpoint size or SHA-256 mismatch; partial download kept for inspection/retry.")
    part.replace(target)
    print(f"Checkpoint downloaded and SHA-256 verified: {target.name}")


def ensure_model(target: Path) -> None:
    if verified(target, MODEL_SIZE, MODEL_SHA256):
        print(f"Checkpoint already verified: {target.name}")
        return
    part = target.with_suffix(target.suffix + ".part")
    downloaded = part.stat().st_size if part.exists() else 0
    if downloaded > MODEL_SIZE:
        downloaded = 0
    if shutil.disk_usage(ROOT).free < MODEL_SIZE - downloaded + 1024 ** 3:
        raise RuntimeError("Not enough free space to finish the SDXL checkpoint download.")
    download_model(target)


def install_main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Install optional ComfyUI + SDXL-Lightning (about 7 GB checkpoint)")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--python", default="3.12", help="Version/interpreter for ComfyUI's separate venv")
    parser.add_argument("--skip-model", action="store_true", help="Install ComfyUI without downloading SDXL")
    args = parser.parse_args(argv)
    repo = ROOT / "engines" / "ComfyUI"
    environment = local_env(ROOT)
    try:
        for tool in ("git", "uv"):
            if not shutil.which(tool):
                raise RuntimeError(f"{tool} is required; see README.md")
        if args.device == "cpu":
            print("CPU mode: SDXL image generation is slow; stock images do not require ComfyUI.")
        ensure_repo(repo, "https://github.com/Comfy-Org/ComfyUI.git", "v0.38.0")
        if not python_path(repo / ".venv").exists():
            run(["uv", "venv", repo / ".venv", "--python", args.python], env=environment)
        index = "https://download.pytorch.org/whl/" + ("cpu" if args.device == "cpu" else "cu130")
        command = ["uv", "pip", "install", "--python", python_path(repo / ".venv"),
                   "torch", "torchvision", "torchaudio", "--index-url", index]
        marker = repo / ".factory-device"
        if marker.exists() and marker.read_text(encoding="utf-8").strip() != args.device:
            for package in ("torch", "torchvision", "torchaudio"):
                command += ["--reinstall-package", package]
        run(command, cwd=repo, env=environment)
        run(["uv", "pip", "install", "--python", python_path(repo / ".venv"), "-r", "requirements.txt"],
            cwd=repo, env=environment)
        (repo / ".factory-device").write_text(args.device, encoding="utf-8")
        if not args.skip_model:
            ensure_model(repo / "models" / "checkpoints" / MODEL_NAME)
        print("Start ComfyUI: python3 chay-comfyui.py")
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"ComfyUI setup failed: {exc}", file=sys.stderr)
        return 1


def launch_command(repo: Path, port: int, device: str | None) -> list[str]:
    marker = repo / ".factory-device"
    if device is None:
        device = marker.read_text(encoding="utf-8").strip() if marker.exists() else "cpu"
    command = [*venv_python(repo / ".venv"), str(repo / "main.py"),
               "--listen", "127.0.0.1", "--port", str(port), "--disable-auto-launch"]
    if device == "cpu":
        command.append("--cpu")
    return command


def launch_main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Start local ComfyUI (Ctrl+C to stop)")
    parser.add_argument("--port", type=int, default=8188)
    parser.add_argument("--device", choices=("cpu", "cuda"), help="Default: device selected during setup")
    args = parser.parse_args(argv)
    repo = ROOT / "engines" / "ComfyUI"
    portable = ROOT / "engines" / "ComfyUI_windows_portable"
    try:
        if (repo / "main.py").exists() and python_path(repo / ".venv").exists():
            command = launch_command(repo, args.port, args.device)
            cwd = repo
        elif sys.platform == "win32" and (portable / "python_embeded" / "python.exe").exists():
            command = [str(portable / "python_embeded" / "python.exe"), "-s", "ComfyUI/main.py",
                       "--windows-standalone-build", "--listen", "127.0.0.1", "--port", str(args.port),
                       "--disable-auto-launch"]
            if args.device == "cpu":
                command.append("--cpu")
            cwd = portable
        else:
            raise RuntimeError("ComfyUI is not installed. Run python3 cai-comfyui.py first.")
        return subprocess.run(command, cwd=cwd, env=local_env(ROOT)).returncode
    except KeyboardInterrupt:
        return 130
    except (OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
