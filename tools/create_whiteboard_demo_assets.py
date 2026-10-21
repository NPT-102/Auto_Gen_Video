"""Create the deterministic assets for content/demo/whiteboard-2fa.json.

They intentionally use a few large, separated shapes.  This lets us review
the Whiteboard engine's layer ordering, retained drawings and camera movement
without depending on an image-generation API.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "whiteboard-demo"
SIZE = (1080, 1920)
PAPER = "#f8f6ef"
INK = "#20252a"
BLUE = "#3b82f6"
ORANGE = "#f59e0b"
GREEN = "#24a36b"
RED = "#e45858"


def sheet():
    image = Image.new("RGB", SIZE, PAPER)
    return image, ImageDraw.Draw(image)


def stroke(draw, points, fill=INK, width=18):
    draw.line(points, fill=fill, width=width, joint="curve")


def box(draw, xy, fill="#ffffff", width=18, radius=36):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=INK, width=width)


def lock(draw, x, y, scale=1.0, colour=ORANGE, broken=False):
    w, h = int(180 * scale), int(150 * scale)
    draw.rounded_rectangle((x, y + int(88 * scale), x + w, y + h + int(88 * scale)), radius=int(24 * scale), fill=colour, outline=INK, width=max(6, int(13 * scale)))
    if broken:
        stroke(draw, [(x + int(32 * scale), y + int(88 * scale)), (x + int(32 * scale), y + int(40 * scale)), (x + int(58 * scale), y + int(15 * scale)), (x + int(89 * scale), y + int(12 * scale))], width=max(6, int(13 * scale)))
        stroke(draw, [(x + int(112 * scale), y + int(12 * scale)), (x + int(143 * scale), y + int(31 * scale)), (x + int(150 * scale), y + int(62 * scale)), (x + int(150 * scale), y + int(88 * scale))], width=max(6, int(13 * scale)))
        stroke(draw, [(x + int(93 * scale), y + int(1 * scale)), (x + int(108 * scale), y + int(30 * scale))], fill=RED, width=max(6, int(12 * scale)))
    else:
        draw.arc((x + int(26 * scale), y, x + int(154 * scale), y + int(150 * scale)), 180, 360, fill=INK, width=max(6, int(13 * scale)))
    draw.ellipse((x + int(80 * scale), y + int(142 * scale), x + int(102 * scale), y + int(164 * scale)), fill=INK)
    stroke(draw, [(x + int(91 * scale), y + int(153 * scale)), (x + int(91 * scale), y + int(177 * scale))], width=max(5, int(9 * scale)))


def shield(draw, x, y, scale=1.0, colour=BLUE, checked=False):
    pts = [(x + 110 * scale, y), (x + 220 * scale, y + 45 * scale), (x + 205 * scale, y + 185 * scale), (x + 110 * scale, y + 270 * scale), (x + 15 * scale, y + 185 * scale), (x, y + 45 * scale)]
    draw.polygon(pts, fill=colour, outline=INK)
    stroke(draw, pts + [pts[0]], width=max(7, int(15 * scale)))
    if checked:
        stroke(draw, [(x + 52 * scale, y + 135 * scale), (x + 94 * scale, y + 178 * scale), (x + 171 * scale, y + 86 * scale)], fill="#ffffff", width=max(8, int(19 * scale)))


def phone(draw, x, y, scale=1.0):
    w, h = int(290 * scale), int(520 * scale)
    box(draw, (x, y, x + w, y + h), fill="#ffffff", width=max(7, int(15 * scale)), radius=int(44 * scale))
    stroke(draw, [(x + int(105 * scale), y + int(42 * scale)), (x + int(185 * scale), y + int(42 * scale))], width=max(5, int(10 * scale)))
    draw.ellipse((x + int(127 * scale), y + int(456 * scale), x + int(163 * scale), y + int(492 * scale)), outline=INK, width=max(5, int(8 * scale)))
    draw.rounded_rectangle((x + int(42 * scale), y + int(115 * scale), x + int(248 * scale), y + int(345 * scale)), radius=int(22 * scale), fill="#dbeafe", outline=INK, width=max(5, int(9 * scale)))
    for xx in (78, 145, 212):
        draw.ellipse((x + int(xx * scale), y + int(385 * scale), x + int((xx + 22) * scale), y + int(407 * scale)), fill=BLUE)


def star(draw, x, y, colour=ORANGE):
    stroke(draw, [(x - 38, y), (x + 38, y)], fill=colour, width=13)
    stroke(draw, [(x, y - 38), (x, y + 38)], fill=colour, width=13)
    stroke(draw, [(x - 28, y - 28), (x + 28, y + 28)], fill=colour, width=10)
    stroke(draw, [(x + 28, y - 28), (x - 28, y + 28)], fill=colour, width=10)


def scene_1():
    image, draw = sheet()
    # laptop
    box(draw, (88, 640, 530, 985), fill="#dbeafe")
    draw.rectangle((132, 690, 486, 920), fill="#ffffff", outline=INK, width=12)
    stroke(draw, [(55, 1025), (566, 1025)], width=24)
    # broken lock is deliberately separate from the laptop
    lock(draw, 650, 650, 1.55, RED, broken=True)
    # warning sign
    draw.polygon([(840, 1180), (990, 1450), (690, 1450)], fill="#fff0c7", outline=INK)
    stroke(draw, [(840, 1180), (990, 1450), (690, 1450), (840, 1180)], width=16)
    stroke(draw, [(840, 1270), (840, 1360)], fill=RED, width=22)
    draw.ellipse((828, 1390, 852, 1414), fill=RED)
    star(draw, 190, 1280, BLUE)
    image.save(OUT / "01-password-risk.png")


def scene_2():
    image, draw = sheet()
    phone(draw, 120, 600, 1.35)
    shield(draw, 630, 525, 1.45, BLUE, checked=False)
    lock(draw, 698, 1060, 1.2, ORANGE)
    # connection arrows are spaced away from objects to keep layers separate
    stroke(draw, [(495, 920), (575, 920)], fill=GREEN, width=17)
    stroke(draw, [(550, 885), (585, 920), (550, 955)], fill=GREEN, width=17)
    star(draw, 225, 1430, ORANGE)
    star(draw, 880, 1435, BLUE)
    image.save(OUT / "02-second-layer.png")


def scene_3():
    image, draw = sheet()
    # Four one-time-code cards, then phone, then a green approval mark.
    for i, value in enumerate(("8", "4", "2", "1")):
        x = 92 + i * 238
        box(draw, (x, 620, x + 176, 825), fill="#ffffff", width=13, radius=26)
        font = ImageFont.truetype("arialbd.ttf", 112)
        draw.text((x + 54, 652), value, fill=INK, font=font)
    phone(draw, 155, 1010, 1.16)
    shield(draw, 700, 1030, 1.12, GREEN, checked=True)
    stroke(draw, [(650, 1315), (720, 1384)], fill=GREEN, width=16)
    stroke(draw, [(688, 1384), (750, 1384)], fill=GREEN, width=16)
    image.save(OUT / "03-one-time-code.png")


def scene_4():
    image, draw = sheet()
    shield(draw, 395, 570, 2.05, GREEN, checked=True)
    # Checklist cards, with enough whitespace that each is a drawable object.
    for y, colour in ((1080, BLUE), (1260, ORANGE), (1440, GREEN)):
        box(draw, (160, y, 920, y + 112), fill="#ffffff", width=12, radius=28)
        draw.ellipse((205, y + 32, 253, y + 80), fill=colour, outline=INK, width=6)
        stroke(draw, [(335, y + 56), (745, y + 56)], width=12)
    star(draw, 178, 705, ORANGE)
    star(draw, 900, 705, BLUE)
    image.save(OUT / "04-turn-on-2fa.png")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    scene_1(); scene_2(); scene_3(); scene_4()
    print(f"Wrote 4 images to {OUT}")
