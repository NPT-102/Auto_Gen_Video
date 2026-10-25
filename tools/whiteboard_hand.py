"""Rasterise assets/whiteboard/hand-marker.svg into the transparent PNG the whiteboard engine overlays.

    .venv/Scripts/python.exe tools/whiteboard_hand.py [--size 900] [--preview preview.png]

The SVG puts the marker tip at (60, 60) of its 900×900 viewBox; hand-marker.json records that anchor in PNG pixels so
the compositor can place the tip exactly on the point being drawn. Chrome (Playwright) renders the SVG, so gradients
and the drop shadow come out the same as in a browser.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets" / "whiteboard"
SVG = ASSETS / "hand-marker.svg"
TIP = (60, 60)   # toạ độ đầu bút trong viewBox 900×900 của SVG
COPIES = [ROOT / "engines" / "whiteboard-lab" / "lab", ROOT / "engines" / "remotion-whiteboard" / "public" / "whiteboard"]


def chrome() -> str | None:
    import sys
    sys.path.insert(0, str(ROOT))
    from factory.config import CHROME   # noqa: E402  (cùng cách tìm Chrome với các engine khác)
    return str(CHROME) if CHROME.exists() else None


def render(size: int, out: Path, preview: Path | None) -> dict:
    svg = SVG.read_text(encoding="utf-8").replace('width="900" height="900"', f'width="{size}" height="{size}"')
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=chrome())
        page = browser.new_page(viewport={"width": size, "height": size}, device_scale_factor=1)
        page.set_content(f"<html><body style='margin:0;background:transparent'>{svg}</body></html>")
        page.locator("svg").screenshot(path=str(out), omit_background=True)
        if preview:
            page.set_content(f"<html><body style='margin:0;background:#fbfaf6'>{svg}</body></html>")
            page.locator("svg").screenshot(path=str(preview))
        browser.close()
    meta = {"image": out.name, "size": size, "tip": [round(TIP[0] * size / 900, 2), round(TIP[1] * size / 900, 2)]}
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    # bản sao cho Whiteboard Lab (clip MP4 có bàn tay) và cho Remotion (bàn tay vẽ đè lên các lớp)
    for folder in COPIES:
        folder.mkdir(parents=True, exist_ok=True)
        for f in (out, out.with_suffix(".json")):
            (folder / f.name).write_bytes(f.read_bytes())
    return meta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=900)
    ap.add_argument("--preview", type=Path)
    a = ap.parse_args()
    print(json.dumps(render(a.size, ASSETS / "hand-marker.png", a.preview)))


if __name__ == "__main__":
    main()
