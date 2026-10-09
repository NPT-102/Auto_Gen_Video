"""Tự vẽ ảnh bằng ComfyUI + SDXL-Lightning trên GPU của máy, không cần làm video.

    vf-python.cmd -m factory.ve_anh "a misty lotus pond at dawn, soft golden light" -n 4
    vf-python.cmd -m factory.ve_anh "hồ sen buổi sớm có sương" --dich -n 4     (Gemini viết lại thành mô tả tiếng Anh)

Bật chay-comfyui.cmd trước. Ảnh dọc 768×1344 (9:16), kiểu ảnh chụp, lưu ở anh-ve/<ngày-giờ>-<mô tả>/ kèm prompt.txt.
Mỗi ảnh một seed khác nhau; cùng mô tả + cùng số thứ tự thì ra lại đúng ảnh cũ (lấy từ cache .cache/beats/ai/).
SDXL hiểu tiếng Anh tốt hơn hẳn tiếng Việt — viết tiếng Việt thì thêm --dich.
"""

import argparse
import shutil
import sys
import time

from .beats import _comfyui, comfyui_url
from .config import ROOT
from .spec import slugify

OUT = ROOT / "anh-ve"
REWRITE = """Rewrite this image idea as ONE English prompt (15-30 words) for the SDXL image model: concrete subject,
setting, action, lighting and camera framing, realistic photo. No text, letters or logos in the image.
Idea: {idea}
Return only the prompt."""


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Vẽ ảnh bằng ComfyUI + SDXL-Lightning (bật chay-comfyui.cmd trước)")
    ap.add_argument("mo_ta", help="mô tả ảnh, nên viết bằng tiếng Anh")
    ap.add_argument("-n", type=int, default=4, help="số ảnh (mặc định 4)")
    ap.add_argument("--dich", action="store_true", help="nhờ Gemini viết lại mô tả thành prompt tiếng Anh")
    a = ap.parse_args()
    prompt = " ".join(a.mo_ta.split())
    if a.dich:
        from .llm import _call_gemini
        prompt = " ".join(_call_gemini(REWRITE.format(idea=prompt), json_mode=False).split()).strip('"')
        print(f"prompt: {prompt}")
    dest = OUT / f"{time.strftime('%Y%m%d-%H%M%S')}-{slugify(a.mo_ta, 40)}"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "prompt.txt").write_text(prompt + "\n", encoding="utf-8")
    t0 = time.time()
    for k in range(a.n):
        img = _comfyui(prompt, print, variant=k)
        if not img:
            print(f"không vẽ được - ComfyUI ở {comfyui_url()} đã bật chưa (chay-comfyui.cmd)?")
            if not k:
                shutil.rmtree(dest, ignore_errors=True)
                if not any(OUT.iterdir()):
                    OUT.rmdir()
            return 1
        out = dest / f"{k + 1:02d}.jpg"
        shutil.copy2(img, out)
        print(f"[{time.time() - t0:5.1f}s] {out}")
    print(f"Xong {a.n} ảnh ở {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
