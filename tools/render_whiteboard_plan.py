"""Render a declarative whiteboard scene into independent PNG object layers.

This deliberately runs with Whiteboard Lab's Python interpreter: it already
has Pillow, while the Factory runtime does not need another image dependency.
Input coordinates are normalized (0..1) against a 1080x1920 board.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


W, H = 1080, 1920
PAPER, INK = "#f8f6ef", "#20252a"
COLOURS = {"blue": "#3b82f6", "orange": "#f59e0b", "green": "#24a36b", "red": "#e45858", "paper": "#ffffff"}


def colour(value: str | None, default: str) -> str:
    return COLOURS.get(str(value or "").lower(), value or default)


def point(item: dict) -> tuple[int, int, float]:
    return round(float(item.get("x", 0)) * W), round(float(item.get("y", 0)) * H), float(item.get("scale", 1))


def stroke(draw: ImageDraw.ImageDraw, points, fill=INK, width=18):
    draw.line(points, fill=fill, width=max(1, round(width)), joint="curve")


def box(draw: ImageDraw.ImageDraw, xy, fill="#ffffff", width=18, radius=36):
    draw.rounded_rectangle(xy, radius=max(1, round(radius)), fill=fill, outline=INK, width=max(1, round(width)))


def draw_lock(draw, x, y, s, c, broken=False):
    w, h, p = 180 * s, 150 * s, max(6, 13 * s)
    draw.rounded_rectangle((x, y + 88 * s, x + w, y + h + 88 * s), radius=24 * s, fill=c, outline=INK, width=round(p))
    if broken:
        stroke(draw, [(x + 32*s, y + 88*s), (x + 32*s, y + 40*s), (x + 58*s, y + 15*s), (x + 89*s, y + 12*s)], width=p)
        stroke(draw, [(x + 112*s, y + 12*s), (x + 143*s, y + 31*s), (x + 150*s, y + 62*s), (x + 150*s, y + 88*s)], width=p)
        stroke(draw, [(x + 93*s, y), (x + 108*s, y + 30*s)], fill=COLOURS["red"], width=12*s)
    else:
        draw.arc((x + 26*s, y, x + 154*s, y + 150*s), 180, 360, fill=INK, width=round(p))
    draw.ellipse((x + 80*s, y + 142*s, x + 102*s, y + 164*s), fill=INK)
    stroke(draw, [(x + 91*s, y + 153*s), (x + 91*s, y + 177*s)], width=9*s)


def draw_shield(draw, x, y, s, c, checked=False):
    pts = [(x + 110*s, y), (x + 220*s, y + 45*s), (x + 205*s, y + 185*s), (x + 110*s, y + 270*s), (x + 15*s, y + 185*s), (x, y + 45*s)]
    draw.polygon(pts, fill=c)
    stroke(draw, pts + [pts[0]], width=15*s)
    if checked:
        stroke(draw, [(x + 52*s, y + 135*s), (x + 94*s, y + 178*s), (x + 171*s, y + 86*s)], fill="#ffffff", width=19*s)


def draw_phone(draw, x, y, s):
    w, h, p = 290*s, 520*s, max(7, 15*s)
    box(draw, (x, y, x+w, y+h), width=p, radius=44*s)
    stroke(draw, [(x + 105*s, y + 42*s), (x + 185*s, y + 42*s)], width=10*s)
    draw.ellipse((x + 127*s, y + 456*s, x + 163*s, y + 492*s), outline=INK, width=round(8*s))
    draw.rounded_rectangle((x + 42*s, y + 115*s, x + 248*s, y + 345*s), radius=22*s, fill="#dbeafe", outline=INK, width=round(9*s))
    for xx in (78, 145, 212):
        draw.ellipse((x + xx*s, y + 385*s, x + (xx+22)*s, y + 407*s), fill=COLOURS["blue"])


def draw_laptop(draw, x, y, s):
    box(draw, (x, y, x + 442*s, y + 345*s), fill="#dbeafe", width=18*s)
    draw.rectangle((x + 44*s, y + 50*s, x + 398*s, y + 280*s), fill="#ffffff", outline=INK, width=round(12*s))
    stroke(draw, [(x - 33*s, y + 385*s), (x + 478*s, y + 385*s)], width=24*s)


def draw_warning(draw, x, y, s):
    pts = [(x + 150*s, y), (x + 300*s, y + 270*s), (x, y + 270*s)]
    draw.polygon(pts, fill="#fff0c7")
    stroke(draw, pts + [pts[0]], width=16*s)
    stroke(draw, [(x + 150*s, y + 90*s), (x + 150*s, y + 180*s)], fill=COLOURS["red"], width=22*s)
    draw.ellipse((x + 138*s, y + 210*s, x + 162*s, y + 234*s), fill=COLOURS["red"])


def draw_code(draw, x, y, s, value):
    digits = str(value or "8421")[:6]
    font = safe_font(round(112*s))
    for i, digit in enumerate(digits):
        xx = x + i * 238*s
        box(draw, (xx, y, xx + 176*s, y + 205*s), width=13*s, radius=26*s)
        draw.text((xx + 54*s, y + 38*s), digit, fill=INK, font=font)


def draw_checklist(draw, x, y, s):
    for index, c in enumerate(("blue", "orange", "green")):
        yy = y + index * 180*s
        box(draw, (x, yy, x + 760*s, yy + 112*s), width=12*s, radius=28*s)
        draw.ellipse((x + 45*s, yy + 32*s, x + 93*s, yy + 80*s), fill=COLOURS[c], outline=INK, width=round(6*s))
        stroke(draw, [(x + 175*s, yy + 56*s), (x + 585*s, yy + 56*s)], width=12*s)


def draw_arrow(draw, x, y, s, item):
    x2 = round(float(item.get("to_x", item.get("x", 0))) * W)
    y2 = round(float(item.get("to_y", item.get("y", 0))) * H)
    c = colour(item.get("color"), COLOURS["green"])
    stroke(draw, [(x, y), (x2, y2)], fill=c, width=17*s)
    dx, dy = x2 - x, y2 - y
    if abs(dx) >= abs(dy):
        sign = 1 if dx >= 0 else -1
        stroke(draw, [(x2 - sign*34*s, y2 - 34*s), (x2, y2), (x2 - sign*34*s, y2 + 34*s)], fill=c, width=17*s)
    else:
        sign = 1 if dy >= 0 else -1
        stroke(draw, [(x2 - 34*s, y2 - sign*34*s), (x2, y2), (x2 + 34*s, y2 - sign*34*s)], fill=c, width=17*s)


def draw_star(draw, x, y, s, c):
    stroke(draw, [(x - 38*s, y), (x + 38*s, y)], fill=c, width=13*s)
    stroke(draw, [(x, y - 38*s), (x, y + 38*s)], fill=c, width=13*s)
    stroke(draw, [(x - 28*s, y - 28*s), (x + 28*s, y + 28*s)], fill=c, width=10*s)
    stroke(draw, [(x + 28*s, y - 28*s), (x - 28*s, y + 28*s)], fill=c, width=10*s)


def draw_bulb(draw, x, y, s, c):
    draw.ellipse((x, y, x + 180*s, y + 180*s), fill="#fff5d7", outline=INK, width=round(15*s))
    stroke(draw, [(x + 55*s, y + 190*s), (x + 125*s, y + 190*s)], width=15*s)
    stroke(draw, [(x + 66*s, y + 218*s), (x + 114*s, y + 218*s)], width=15*s)
    for dx, dy in ((90, -55), (-42, 15), (222, 15), (0, 155), (180, 155)):
        stroke(draw, [(x + dx*s, y + dy*s), (x + dx*s + 18*s, y + dy*s)], fill=c, width=11*s)


def draw_chart(draw, x, y, s, c):
    stroke(draw, [(x, y + 330*s), (x + 340*s, y + 330*s)], width=16*s)
    stroke(draw, [(x, y + 330*s), (x, y + 30*s)], width=16*s)
    for index, height in enumerate((100, 190, 275)):
        xx = x + (58 + index * 94)*s
        draw.rounded_rectangle((xx, y + (330-height)*s, xx + 58*s, y + 330*s), radius=12*s, fill=c, outline=INK, width=round(9*s))
    stroke(draw, [(x + 35*s, y + 245*s), (x + 150*s, y + 155*s), (x + 245*s, y + 195*s), (x + 330*s, y + 55*s)], fill=COLOURS["green"], width=14*s)


def draw_coin(draw, x, y, s, c):
    draw.ellipse((x, y, x + 190*s, y + 190*s), fill=c, outline=INK, width=round(15*s))
    draw.ellipse((x + 35*s, y + 35*s, x + 155*s, y + 155*s), outline="#ffffff", width=round(10*s))
    stroke(draw, [(x + 95*s, y + 54*s), (x + 95*s, y + 136*s)], fill="#ffffff", width=12*s)


def draw_cloud(draw, x, y, s, c):
    circles = [(0, 70, 120), (80, 20, 155), (190, 65, 120), (65, 90, 200)]
    for dx, dy, size in circles:
        draw.ellipse((x + dx*s, y + dy*s, x + (dx+size)*s, y + (dy+size)*s), fill="#dbeafe", outline=INK, width=round(13*s))
    stroke(draw, [(x + 45*s, y + 210*s), (x + 290*s, y + 210*s)], fill=c, width=20*s)


def draw_server(draw, x, y, s, c):
    for index in range(3):
        yy = y + index * 102*s
        box(draw, (x, yy, x + 270*s, yy + 76*s), fill="#ffffff", width=12*s, radius=16*s)
        draw.ellipse((x + 26*s, yy + 27*s, x + 48*s, yy + 49*s), fill=c)
        stroke(draw, [(x + 84*s, yy + 38*s), (x + 220*s, yy + 38*s)], width=8*s)


def safe_font(size: int):
    for name in ("arialbd.ttf", "Arial Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def draw_object(layer: Image.Image, item: dict) -> None:
    draw = ImageDraw.Draw(layer)
    kind = str(item.get("kind", "")).lower()
    x, y, s = point(item)
    c = colour(item.get("color"), COLOURS["blue"])
    if kind == "laptop": draw_laptop(draw, x, y, s)
    elif kind == "lock": draw_lock(draw, x, y, s, c, bool(item.get("broken")))
    elif kind == "phone": draw_phone(draw, x, y, s)
    elif kind == "shield": draw_shield(draw, x, y, s, c, bool(item.get("checked")))
    elif kind == "warning": draw_warning(draw, x, y, s)
    elif kind == "code": draw_code(draw, x, y, s, item.get("value"))
    elif kind == "checklist": draw_checklist(draw, x, y, s)
    elif kind == "arrow": draw_arrow(draw, x, y, s, item)
    elif kind == "star": draw_star(draw, x, y, s, c)
    elif kind == "bulb": draw_bulb(draw, x, y, s, c)
    elif kind == "chart": draw_chart(draw, x, y, s, c)
    elif kind == "coin": draw_coin(draw, x, y, s, c)
    elif kind == "cloud": draw_cloud(draw, x, y, s, c)
    elif kind == "server": draw_server(draw, x, y, s, c)
    else: raise ValueError(f"unknown whiteboard object kind: {kind}")


def render(plan: dict, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    result = []
    # Accept the compact `whiteboard_plan` field too so a content JSON can be
    # previewed directly from the command line.
    scene_plans = plan.get("whiteboard_plan") if "whiteboard_plan" in plan else plan.get("scenes")
    for scene_index, scene in enumerate(scene_plans or [], 1):
        scene_dir = out_dir / f"scene-{scene_index:02d}"
        scene_dir.mkdir(parents=True, exist_ok=True)
        composite = Image.new("RGBA", (W, H), PAPER)
        layers = []
        for object_index, item in enumerate(scene.get("objects") or [], 1):
            shape = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            draw_object(shape, item)
            bbox = shape.getbbox()
            if bbox is None: continue
            layer = Image.new("RGBA", (W, H), PAPER)
            layer.alpha_composite(shape)
            name = f"layer-{object_index:02d}.png"
            layer.convert("RGB").save(scene_dir / name)
            composite.alpha_composite(shape)
            x0, y0, x1, y1 = bbox
            layers.append({"file": f"scene-{scene_index:02d}/{name}", "weight": max(1, (x1-x0)*(y1-y0)) ** 0.5,
                           "bbox": {"x": round(x0/W, 5), "y": round(y0/H, 5), "w": round((x1-x0)/W, 5), "h": round((y1-y0)/H, 5)}})
        if not layers: raise ValueError(f"scene {scene_index} has no drawable objects")
        composite_name = f"scene-{scene_index:02d}/composite.png"
        composite.convert("RGB").save(out_dir / composite_name)
        result.append({"layers": layers, "composite": composite_name})
    return {"scenes": result}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(render(json.loads(args.plan.read_text(encoding="utf-8")), args.out_dir), ensure_ascii=False))


if __name__ == "__main__":
    main()
