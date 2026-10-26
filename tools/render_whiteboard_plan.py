"""Render a declarative whiteboard scene into independent PNG object layers.

This deliberately runs with Whiteboard Lab's Python interpreter: it already
has Pillow, while the Factory runtime does not need another image dependency.
Input coordinates are normalized (0..1) against a 1080x1920 board.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


W, H = 1080, 1920
PAPER, INK = "#fbfaf6", "#242424"
# Keep the palette deliberately small.  A whiteboard page is readable because
# colour is an accent, not because every object has its own full illustration.
COLOURS = {"blue": "#5c8fbf", "orange": "#d9874d", "green": "#6b9d79", "red": "#ca6961", "pink": "#d58b9e", "paper": "#ffffff"}
VIETNAMESE_FONT = Path(__file__).resolve().parents[1] / "engines" / "remotion-whiteboard" / "public" / "fonts" / "BeVietnamPro-Medium.ttf"
# Every page is scaled and centred into this part of the 9:16 board, so a plan whose objects are small, crowded into
# one corner or hanging off the edge (an LLM storyboard often is) still fills the frame. The bottom edge leaves room
# for platform UI; a plan sets "safe" to change it (the engine raises it when captions are drawn).
SAFE = {"x0": 0.06, "y0": 0.07, "x1": 0.94, "y1": 0.93}
MAX_GROW = 1.5


def colour(value: str | None, default: str) -> str:
    return COLOURS.get(str(value or "").lower(), value or default)


def point(item: dict) -> tuple[int, int, float]:
    return round(float(item.get("x", 0)) * W), round(float(item.get("y", 0)) * H), float(item.get("scale", 1))


def stroke(draw: ImageDraw.ImageDraw, points, fill=INK, width=18):
    width = max(1, round(width))
    draw.line(points, fill=fill, width=width, joint="curve")
    # round caps, like a marker tip: PIL ends a line square, which shows as a notch at every stick-figure limb
    if width >= 3:
        r = width / 2
        for px, py in (points[0], points[-1]):
            draw.ellipse((px - r, py - r, px + r, py + r), fill=fill)


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


def draw_phone(draw, x, y, s, item):
    w, h, p = 290*s, 520*s, max(7, 15*s)
    # A plain phone is line art.  Keeping its body/screen transparent lets
    # one pen draw it continuously.  A plan can request a coloured display
    # explicitly, which then needs outline first and fill second.
    box(draw, (x, y, x+w, y+h), fill=None, width=p, radius=44*s)
    stroke(draw, [(x + 105*s, y + 42*s), (x + 185*s, y + 42*s)], width=10*s)
    draw.ellipse((x + 127*s, y + 456*s, x + 163*s, y + 492*s), outline=INK, width=round(8*s))
    screen = item.get("screen_color")
    draw.rounded_rectangle((x + 42*s, y + 115*s, x + 248*s, y + 345*s), radius=22*s,
                           fill=colour(screen, "#dbeafe") if screen else None, outline=INK, width=round(9*s))
    if screen:
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
    # Head along the shaft's own direction: the old horizontal/vertical heads bent a diagonal arrow into a ">" mark.
    angle = math.atan2(y2 - y, x2 - x)
    head = 44 * s
    wing = [(x2 + head * math.cos(angle + turn), y2 + head * math.sin(angle + turn)) for turn in (2.62, -2.62)]
    stroke(draw, [wing[0], (x2, y2), wing[1]], fill=c, width=17*s)


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


def draw_text_lines(draw, x, y, s, text, c=INK, align="left", label=None):
    """Write a loose, readable label directly on the board.

    These labels intentionally have no card or UI chrome around them.  Text is
    another thing the hand draws, just like an arrow or a stick figure.
    """
    text = str(text or "").strip()
    if not text:
        return
    # Legible on a phone: a .6 heading is ~67 px on the 1080 px board (it was 51 px, smaller than caption text).
    size = max(44, round(float(s) * 112))
    font = safe_font(size)
    room = (W - 48 - x) if align != "center" else 2 * min(x, W - x) - 96
    max_width = max(220, min(round(900 * float(s)), room))
    lines = balanced_lines(draw, text.split(), font, max_width)
    for index, line in enumerate(lines[:3]):
        width = draw.textbbox((0, 0), line, font=font)[2]
        xx = x - width // 2 if align == "center" else x
        draw.text((xx, y + index * size * 1.08), line, fill=c, font=font, stroke_width=max(0, round(s * 0.7)))
    if label:
        small = safe_font(max(30, round(size * .5)))
        draw.text((x, y + len(lines[:3]) * size * 1.14), str(label), fill=colour("green", COLOURS["green"]), font=small)


def balanced_lines(draw, words: list[str], font, max_width: int) -> list[str]:
    """Wrap into as few lines as max_width allows, then even them out ("XÁC THỰC / HAI LỚP", never a lone last word)."""
    def wrap(limit: float) -> list[str]:
        lines, line = [], []
        for word in words:
            candidate = " ".join(line + [word])
            if line and draw.textbbox((0, 0), candidate, font=font)[2] > limit:
                lines.append(" ".join(line)); line = [word]
            else:
                line.append(word)
        return lines + ([" ".join(line)] if line else [])
    lines = wrap(max_width)
    if len(lines) < 2:
        return lines
    low, high = max(draw.textbbox((0, 0), w, font=font)[2] for w in words), float(max_width)
    for _ in range(18):   # narrowest width that still needs no extra line
        mid = (low + high) / 2
        if len(wrap(mid)) <= len(lines):
            high = mid
        else:
            low = mid
    return wrap(high)


def draw_stick_person(draw, x, y, s, c, pose="stand"):
    p = max(5, round(13*s))
    draw.ellipse((x + 56*s, y, x + 156*s, y + 100*s), outline=INK, width=p)
    stroke(draw, [(x + 106*s, y + 100*s), (x + 106*s, y + 246*s)], width=p)
    if pose == "point":
        stroke(draw, [(x + 106*s, y + 136*s), (x + 25*s, y + 170*s)], fill=c, width=p)
        stroke(draw, [(x + 106*s, y + 136*s), (x + 204*s, y + 92*s)], fill=c, width=p)
    else:
        stroke(draw, [(x + 106*s, y + 136*s), (x + 30*s, y + 188*s)], width=p)
        stroke(draw, [(x + 106*s, y + 136*s), (x + 182*s, y + 188*s)], width=p)
    stroke(draw, [(x + 106*s, y + 246*s), (x + 44*s, y + 350*s)], width=p)
    stroke(draw, [(x + 106*s, y + 246*s), (x + 168*s, y + 350*s)], width=p)


def draw_books(draw, x, y, s, c):
    p = max(5, round(12*s))
    for index, shift in enumerate((0, -18, 12)):
        yy = y + index * 82*s
        draw.rounded_rectangle((x + shift*s, yy, x + (268 + shift)*s, yy + 68*s), radius=13*s, fill="#ffffff", outline=INK, width=p)
        stroke(draw, [(x + (35 + shift)*s, yy + 34*s), (x + (205 + shift)*s, yy + 34*s)], fill=c if index == 1 else INK, width=max(4, round(7*s)))


def draw_document(draw, x, y, s, c):
    p = max(5, round(12*s))
    w, h = 220*s, 292*s
    draw.polygon([(x, y), (x + w*0.72, y), (x + w, y + h*.25), (x + w, y+h), (x, y+h)], fill="#ffffff", outline=INK)
    stroke(draw, [(x + w*.72, y), (x + w*.72, y + h*.25), (x+w, y+h*.25)], width=p)
    for yy in (.43, .58, .73):
        stroke(draw, [(x + 30*s, y + h*yy), (x + w*.78, y + h*yy)], fill=c if yy == .43 else INK, width=max(4, round(7*s)))


def draw_explosion(draw, x, y, s, c):
    points = []
    for index in range(16):
        angle = math.tau * index / 16 - math.pi / 2
        radius = (120 if index % 2 == 0 else 72) * s
        points.append((x + 125*s + math.cos(angle)*radius, y + 125*s + math.sin(angle)*radius))
    draw.polygon(points, fill="#fff5d7")
    stroke(draw, points + [points[0]], fill=INK, width=max(5, round(12*s)))
    draw.ellipse((x + 93*s, y + 93*s, x + 157*s, y + 157*s), fill=c, outline=INK, width=max(4, round(7*s)))


def draw_atom(layer, draw, x, y, s, c):
    p = max(4, round(9*s))
    cx, cy = x + 135*s, y + 118*s
    for angle in (-45, 0, 45):
        w, h = 250*s, 84*s
        shape = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(shape)
        sd.ellipse((cx-w/2, cy-h/2, cx+w/2, cy+h/2), outline=INK, width=p)
        shape = shape.rotate(angle, center=(cx, cy), resample=Image.Resampling.BICUBIC)
        layer.alpha_composite(shape)
    draw.ellipse((cx-25*s, cy-25*s, cx+25*s, cy+25*s), fill=c, outline=INK, width=p)


def safe_font(size: int):
    # Ink Free looks hand-written but lacks Vietnamese glyphs.  The bundled
    # font is first so words never turn into square replacement characters.
    for name in (VIETNAMESE_FONT, "Inkfree.ttf", "segoepr.ttf", "comic.ttf", "arialbd.ttf", "Arial Bold.ttf"):
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
    elif kind == "phone": draw_phone(draw, x, y, s, item)
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
    elif kind in {"text", "formula", "stat"}:
        draw_text_lines(draw, x, y, s, item.get("text", item.get("value", "")), colour(item.get("color"), INK),
                        str(item.get("align", "left")), item.get("label") if kind == "stat" else None)
    elif kind in {"person", "stick_person"}: draw_stick_person(draw, x, y, s, c, str(item.get("pose", "stand")))
    elif kind in {"books", "paper_stack"}: draw_books(draw, x, y, s, c)
    elif kind in {"document", "paper"}: draw_document(draw, x, y, s, c)
    elif kind in {"explosion", "burst"}: draw_explosion(draw, x, y, s, c)
    elif kind == "atom": draw_atom(layer, draw, x, y, s, c)
    else: raise ValueError(f"unknown whiteboard object kind: {kind}")


def layer_draw_mode(layer: Image.Image, item: dict) -> str:
    """Choose direct ink only for a layer made of thin marks.

    A coloured arrow and a black handwritten label are just pen strokes. A
    lock, shield, or phone with a coloured screen contains a real interior
    area: reveal its outline first, then its fill. Pixel thickness works for
    generated plans and remains correct when a caller changes a shape's
    colour or removes its inner fill.
    """
    kind = str(item.get("kind", "")).lower()
    if kind in {"text", "stat", "formula", "arrow", "star", "person", "stick_person"}:
        return "direct_color"
    if kind == "phone" and not item.get("screen_color"):
        return "direct_color"
    alpha = np.asarray(layer.getchannel("A")) > 10
    if not alpha.any():
        return "direct_color"
    distance = cv2.distanceTransform(alpha.astype(np.uint8), cv2.DIST_L2, 5)
    # Planner strokes are at most about 17px wide on the 1080px board; a
    # region thicker than this is a paintable interior rather than a line.
    return "outline_color" if float(distance.max()) > 12.0 else "direct_color"


def measure(item: dict) -> tuple[int, int, int, int] | None:
    """Pixel box of one object at its planned place, including any part that falls outside the board."""
    big = Image.new("RGBA", (W * 2, H * 2), (0, 0, 0, 0))
    draw_object(big, moved(item, 1.0, W / 2, H / 2))
    box = big.getbbox()
    return None if box is None else (box[0] - W // 2, box[1] - H // 2, box[2] - W // 2, box[3] - H // 2)


def moved(item: dict, k: float, ox: float, oy: float) -> dict:
    """The same object scaled by k about the board origin, then shifted by (ox, oy) pixels."""
    out = dict(item)
    for kx, ky in (("x", "y"), ("to_x", "to_y")):
        if kx in item:
            out[kx] = (float(item[kx]) * W * k + ox) / W
        if ky in item:
            out[ky] = (float(item[ky]) * H * k + oy) / H
    out["scale"] = float(item.get("scale", 1)) * k
    return out


GAP = 30   # px kept clear between two objects on the same page


def separate(items: list[dict]) -> list[dict]:
    """Nudge objects that would be drawn on top of an earlier one on the page, by the smallest move (vertical first).

    Plans often put a label where a bigger number or a box already is. Arrows are left alone: they are meant to
    touch the things they connect."""
    def clash(a, b):
        return a[0] < b[2] + GAP and b[0] < a[2] + GAP and a[1] < b[3] + GAP and b[1] < a[3] + GAP
    steps = sorted(((dx, dy) for dx in range(-480, 481, 16) for dy in range(-480, 481, 16)),
                   key=lambda d: abs(d[0]) * 1.4 + abs(d[1]) + (0 if d[1] >= 0 else 8))
    taken, out = [], []
    for item in items:
        box = None if str(item.get("kind", "")).lower() == "arrow" else measure(item)
        if box is None:
            out.append(item)
            continue
        for dx, dy in steps:
            moved_box = (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)
            if not any(clash(moved_box, other) for other in taken):
                break
        else:
            dx, dy, moved_box = 0, 0, box
        taken.append(moved_box)
        out.append(moved(item, 1.0, dx, dy) if (dx or dy) else item)
    return out


def fit_pages(scenes: list[dict], safe: dict) -> list[list[dict]]:
    """Scale and centre each page (consecutive scenes with the same `page`) into the safe area.

    One transform per page keeps objects drawn in an earlier scene of the page in place when the next scene adds to
    it. Pages are grown at most MAX_GROW times and shrunk only when they overflow."""
    out = [list(scene.get("objects") or []) for scene in scenes]
    start = 0
    while start < len(scenes):
        key = scenes[start].get("page", start + 1)
        end = start
        while end + 1 < len(scenes) and scenes[end + 1].get("page", end + 2) == key:
            end += 1
        # objects of the whole page in drawing order, de-overlapped together, then put back per scene
        flat = [(i, item) for i in range(start, end + 1) for item in out[i]]
        if all(scene.get("separate", True) for scene in scenes[start:end + 1]):
            fixed = separate([item for _, item in flat])
            for i in range(start, end + 1):
                out[i] = [item for (j, _), item in zip(flat, fixed) if j == i]
        boxes = [b for i in range(start, end + 1) for b in (measure(item) for item in out[i]) if b]
        if boxes and all(scene.get("fit", True) for scene in scenes[start:end + 1]):
            x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
            x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
            tx0, ty0, tx1, ty1 = safe["x0"] * W, safe["y0"] * H, safe["x1"] * W, safe["y1"] * H
            k = min((tx1 - tx0) / max(1, x1 - x0), (ty1 - ty0) / max(1, y1 - y0), MAX_GROW)
            ox = tx0 + ((tx1 - tx0) - (x1 - x0) * k) / 2 - x0 * k
            oy = ty0 + ((ty1 - ty0) - (y1 - y0) * k) / 2 - y0 * k
            for i in range(start, end + 1):
                out[i] = [moved(item, k, ox, oy) for item in out[i]]
        start = end + 1
    return out


def render(plan: dict, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    result = []
    # Accept the compact `whiteboard_plan` field too so a content JSON can be
    # previewed directly from the command line.
    scene_plans = plan.get("whiteboard_plan") if "whiteboard_plan" in plan else plan.get("scenes")
    placed = fit_pages(list(scene_plans or []), {**SAFE, **(plan.get("safe") or {})})
    for scene_index, scene in enumerate(scene_plans or [], 1):
        scene_dir = out_dir / f"scene-{scene_index:02d}"
        scene_dir.mkdir(parents=True, exist_ok=True)
        composite = Image.new("RGBA", (W, H), PAPER)
        composite_alpha = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        layers = []
        for object_index, item in enumerate(placed[scene_index - 1], 1):
            shape = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            draw_object(shape, item)
            bbox = shape.getbbox()
            if bbox is None: continue
            draw_mode = layer_draw_mode(shape, item)
            layer = Image.new("RGBA", (W, H), PAPER)
            layer.alpha_composite(shape)
            name = f"layer-{object_index:02d}.png"
            layer.convert("RGB").save(scene_dir / name)
            # Bản trong suốt của cùng lớp: Whiteboard Lab đóng gói sẵn vẽ thẳng từ đây, không phải tách nền giấy
            # (tách theo màu làm mảng trắng bên trong hình — màn hình điện thoại, ô mã số — thành trong suốt).
            alpha_name = f"layer-{object_index:02d}.rgba.png"
            shape.save(scene_dir / alpha_name)
            composite.alpha_composite(shape)
            composite_alpha.alpha_composite(shape)
            x0, y0, x1, y1 = bbox
            layers.append({"file": f"scene-{scene_index:02d}/{name}", "weight": max(1, (x1-x0)*(y1-y0)) ** 0.5,
                           "alpha_file": f"scene-{scene_index:02d}/{alpha_name}",
                            "kind": str(item.get("kind", "")).lower(),
                            "draw_mode": draw_mode,
                           "color": item.get("color"),
                           "at": item.get("at"),
                           "bbox": {"x": round(x0/W, 5), "y": round(y0/H, 5), "w": round((x1-x0)/W, 5), "h": round((y1-y0)/H, 5)}})
        if not layers: raise ValueError(f"scene {scene_index} has no drawable objects")
        composite_name = f"scene-{scene_index:02d}/composite.png"
        composite.convert("RGB").save(out_dir / composite_name)
        composite_alpha.save(out_dir / f"scene-{scene_index:02d}/composite.rgba.png")
        result.append({"layers": layers, "composite": composite_name,
                       "composite_alpha": f"scene-{scene_index:02d}/composite.rgba.png",
                       "page": scene.get("page", scene_index)})
    return {"scenes": result}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(render(json.loads(args.plan.read_text(encoding="utf-8")), args.out_dir), ensure_ascii=False))


if __name__ == "__main__":
    main()
