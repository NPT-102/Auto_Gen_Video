"""In tình trạng cài đặt: key nào đã có, engine nào sẵn sàng, tự vẽ ảnh đã cài / đang bật chưa.

    vf-python.cmd -m factory.status
(cai-dat.cmd tự chạy lệnh này ở bước cuối.)
"""

import sys

import httpx

from .beats import _source, comfyui_url
from .config import CHROME, ENGINES_DIR, MPT_DIR, gemini_api_key, pexels_api_key, setting
from .engines import ENGINES

CKPT = ENGINES_DIR / "ComfyUI_windows_portable" / "ComfyUI" / "models" / "checkpoints" / "sdxl_lightning_4step.safetensors"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    print("Key (.env):")
    print(f"  Gemini      : {'có' if gemini_api_key() else 'CHƯA CÓ - điền GEMINI_API_KEY trong .env'}")
    print(f"  Pexels      : {'có' if pexels_api_key() else 'CHƯA CÓ - điền PEXELS_API_KEY trong .env'}")
    print(f"  ElevenLabs  : {'có' if setting('ELEVENLABS_API_KEY') else 'không (tuỳ chọn, chỉ cho bản podcast)'}")
    print(f"Chrome        : {CHROME if CHROME.exists() else 'KHÔNG THẤY - cài Google Chrome hoặc đặt CHROME_PATH trong .env'}")
    print(f"MoneyPrinterTurbo: {MPT_DIR}")
    print("Engine:")
    ready = 0
    for e in ENGINES.values():
        ok, why = e.check()
        ready += ok
        print(f"  [{'ok' if ok else '--'}] {e.label}" + ("" if ok else f": {why}"))
    try:
        running = httpx.get(f"{comfyui_url()}/system_stats", timeout=2).status_code == 200
    except httpx.HTTPError:
        running = False
    print(f"Tự vẽ ảnh     : {'đã cài' if CKPT.exists() else 'chưa cài (cai-comfyui.cmd)'}"
          f", ComfyUI {'đang chạy' if running else 'chưa bật (chay-comfyui.cmd)'}")
    print(f"Nguồn ảnh mặc định: {_source()}  (đổi bằng IMAGE_SOURCE trong .env hoặc \"image_source\" trong kịch bản)")
    return 0 if ready == len(ENGINES) else 1


if __name__ == "__main__":
    sys.exit(main())
