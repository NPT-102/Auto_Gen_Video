"""Đường dẫn và cấu hình dùng chung của video-factory.

Mọi thiết lập đọc theo thứ tự: biến môi trường → file .env ở thư mục gốc (mẫu: .env.example) → mặc định.
"""

import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # video-factory/
ENGINES_DIR = ROOT / "engines"
CONTENT_DIR = ROOT / "content"
RUNS_DIR = ROOT / "runs"
PUBLISH_DIR = ROOT / "publish"
CACHE_DIR = ROOT / ".cache"
WEB_DIR = Path(__file__).resolve().parent / "web"


def _read_dotenv() -> dict[str, str]:
    env_file = ROOT / ".env"
    values: dict[str, str] = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def setting(name: str, default: str = "") -> str:
    return os.environ.get(name) or _read_dotenv().get(name) or default


def _mpt_dir() -> Path:
    """MoneyPrinterTurbo: MPT_DIR → engines/MoneyPrinterTurbo (cai-dat.cmd clone vào đây) → thư mục nằm cạnh
    video-factory (cách bố trí trên máy dựng hệ thống lần đầu)."""
    if setting("MPT_DIR"):
        return Path(setting("MPT_DIR"))
    inside, beside = ENGINES_DIR / "MoneyPrinterTurbo", ROOT.parent / "MoneyPrinterTurbo"
    return beside if beside.exists() and not inside.exists() else inside


def _chrome() -> Path:
    """Chrome cho HyperFrames, Remotion, AI-auto và xem nhanh: CHROME_PATH → chỗ cài thường gặp → Edge (cùng nhân Chromium)."""
    if setting("CHROME_PATH"):
        return Path(setting("CHROME_PATH"))
    dirs = [os.environ.get(k) for k in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
    found = [Path(d) / "Google" / "Chrome" / "Application" / "chrome.exe" for d in dirs if d]
    found += [Path(d) / "Microsoft" / "Edge" / "Application" / "msedge.exe" for d in dirs[:2] if d]
    return next((p for p in found if p.exists()), Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"))


MPT_DIR = _mpt_dir()
CHROME = _chrome()

PORT = int(setting("FACTORY_PORT", "8600"))
# Số engine render cùng lúc. Máy 32 luồng chạy 2 engine song song thoải mái.
MAX_PARALLEL = int(setting("FACTORY_PARALLEL", "2"))

DEFAULT_VOICE = "vi-VN-HoaiMyNeural"

for d in (CONTENT_DIR, RUNS_DIR, PUBLISH_DIR, CACHE_DIR):
    d.mkdir(parents=True, exist_ok=True)


def gemini_api_key() -> str | None:
    """Key Gemini cho bước viết nháp: biến môi trường → video-factory/.env → config.toml của MoneyPrinterTurbo."""
    key = setting("GEMINI_API_KEY")
    if key:
        return key
    mpt_config = MPT_DIR / "config.toml"
    if mpt_config.exists():
        try:
            data = tomllib.loads(mpt_config.read_text(encoding="utf-8"))
            return (data.get("app", {}) or {}).get("gemini_api_key") or None
        except (tomllib.TOMLDecodeError, OSError):
            return None
    return None


def pexels_api_key() -> str | None:
    """Key Pexels: biến môi trường → video-factory/.env → key đã nhập trong MoneyPrinterTurbo."""
    key = setting("PEXELS_API_KEY")
    if key:
        return key
    try:
        keys = (tomllib.loads((MPT_DIR / "config.toml").read_text(encoding="utf-8")).get("app", {}) or {}).get("pexels_api_keys")
    except (tomllib.TOMLDecodeError, OSError):
        return None
    if isinstance(keys, list):
        keys = next((k for k in keys if k), None)
    return keys or None


def gemini_model() -> str:
    return setting("GEMINI_MODEL", "gemini-flash-latest")
