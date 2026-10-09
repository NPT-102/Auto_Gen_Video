"""Xem nhanh khung hình của template HyperFrames mà không render cả video.

    vf-python.cmd -m factory.preview content/demo/flow-demo.json            # tự chọn khung giữa và cuối mỗi cảnh
    vf-python.cmd -m factory.preview content/demo/flow-demo.json 3,8.5,12   # các giây cụ thể
Kết quả: .cache/preview/<id>.png (các khung ghép ngang).
"""

import subprocess
import sys
from pathlib import Path

from .config import CACHE_DIR, CHROME
from .engines.hyperframes import build_composition
from .spec import load_spec


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    spec = load_spec(Path(sys.argv[1]))
    out_dir = CACHE_DIR / "preview" / spec.id
    data = build_composition(spec, out_dir / "comp", lambda m: None, audio=False)
    if len(sys.argv) > 2:
        times = [float(x) for x in sys.argv[2].split(",")]
    else:
        times = [round(s["start"] + f * (s["end"] - s["start"]), 2) for s in data["scenes"] for f in (0.55, 0.92)]
    for s in data["scenes"]:
        print(f"  {s['type']:8s} {s['start']:6.1f} → {s['end']:6.1f}")

    from playwright.sync_api import sync_playwright

    shots = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(CHROME))
        page = browser.new_page(viewport={"width": 1080, "height": 1920})
        page.goto((out_dir / "comp" / "index.html").as_uri())
        page.evaluate("document.fonts.ready")
        for i, t in enumerate(times):
            page.evaluate("t => renderAt(t)", t)
            f = out_dir / f"f{i:02d}.png"
            page.screenshot(path=str(f))
            shots.append(f)
        browser.close()
    sheet = CACHE_DIR / "preview" / f"{spec.id}.png"
    inputs = sum((["-i", str(f)] for f in shots), [])
    chain = "".join(f"[{i}:v]scale=324:576[v{i}];" for i in range(len(shots))) + "".join(f"[v{i}]" for i in range(len(shots)))
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", f"{chain}hstack=inputs={len(shots)}", str(sheet)], check=True)
    print(f"{sheet}  ({', '.join(str(t) for t in times)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
