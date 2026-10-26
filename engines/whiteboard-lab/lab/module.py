"""Whiteboard Lab đóng gói sẵn trong repo: biến một lớp hình thành clip bàn tay vẽ.

Cùng giao diện dòng lệnh với Whiteboard Lab mà factory/engines/whiteboard.py vẫn gọi:
    python -m lab.module --image layer.png --output clip.mp4 --duration 2.5 --mode outline_color
    python -m lab.module --image scene.png --split-objects out_dir
và thêm ba tuỳ chọn (engine dùng khi thấy lab/capabilities.json):
    --frames-dir DIR   khung PNG trong suốt chỉ có nét vẽ, không có bàn tay (Remotion tự vẽ bàn tay)
    --pen-json FILE    vị trí đầu bút ở từng khung: [x, y, trạng thái] (x, y từ 0 tới 1; 0 nhấc, 1 nét, 2 tô)
    --natural          thời lượng theo độ dài nét (tốc độ tay người), tối đa bằng --duration
Dòng cuối stdout là JSON: {"frames", "duration", "fps", ...}.

Cách vẽ (chế độ outline_color — hình vẽ đơn giản, chữ, mũi tên):
1. Tách nét và mảng màu theo độ dày: phần mảnh (viền mực, chữ, mũi tên màu) là NÉT, phần dày là MẢNG TÔ.
2. Làm mảnh nét thành đường xương (thinning), rồi cho bút đi dọc đường xương: đi thẳng tối đa qua các ngã rẽ, hết
   đường thì nhấc bút sang điểm chưa vẽ gần nhất. Mỗi điểm ảnh của nét hiện ra đúng lúc đầu bút đi qua điểm xương
   gần nó nhất (distanceTransformWithLabels), nên nét lộ ra như được kéo bằng bút chứ không phải hiện dần cả hình.
3. Vẽ hết nét thì tô màu: mỗi mảng màu được quét từ trái sang phải, bút đánh zig-zag theo vệt quét.
Chế độ direct_color (ảnh chụp, tranh nhiều chi tiết): vẽ phác các cạnh (Canny) bằng mực xám trước, rồi quét ra ảnh màu.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
HAND = HERE / "hand-marker.png"
PAPER_RGB = (251, 250, 246)
THICK_PAINT = 26.0    # coloured region wider than a deliberate marker stroke

PEN_SPEED = 1900.0      # px/giây trên đoạn thẳng khi bút chạm giấy (khung 1080×1920); chỗ ngoặt chậm hơn
AIR_SPEED = 4200.0      # px/giây khi nhấc bút sang nét khác
LIFT = 0.02             # giây nhấc + hạ bút cho một bước nhảy rất ngắn; xa hơn thì lâu hơn (xem timing)
THIN = 15.0             # nửa bề dày tối đa (px) để một mảng được coi là nét


# ---------------------------------------------------------------------------------------------------------- ảnh vào
def load_rgba(path: Path) -> np.ndarray:
    """RGBA uint8. Ảnh không có kênh alpha thì coi phần giấy nối với mép ảnh là trong suốt (lòng hình trắng vẫn giữ)."""
    arr = np.asarray(Image.open(path).convert("RGBA")).copy()
    if arr[..., 3].min() < 255:
        return arr
    rgb = arr[..., :3].astype(np.int16)
    h, w = rgb.shape[:2]
    k = max(8, min(h, w) // 40)
    corners = np.concatenate([rgb[:k, :k].reshape(-1, 3), rgb[:k, -k:].reshape(-1, 3),
                              rgb[-k:, :k].reshape(-1, 3), rgb[-k:, -k:].reshape(-1, 3)])
    paper = np.median(corners, axis=0)
    near = (np.max(np.abs(rgb - paper), axis=2) <= 12).astype(np.uint8)
    count, labels = cv2.connectedComponents(near, connectivity=4)
    border = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    background = np.isin(labels, border[border > 0]) & (near > 0)
    arr[..., 3] = np.where(background, 0, 255).astype(np.uint8)
    return arr


def luminance(rgb: np.ndarray) -> np.ndarray:
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def automatic_mode(rgb: np.ndarray, visible: np.ndarray) -> str:
    """Choose drawing order from actual paint regions, not just dark pixels.

    Dark text and black line drawings are still pen marks.  A phone screen,
    shield body, or coloured artwork has a thick non-paper region and needs
    its outline before its fill.  This is also safe for uploaded assets where
    the Factory has no semantic object kind to inspect.
    """
    light = luminance(rgb)
    spread = rgb.max(axis=2) - rgb.min(axis=2)
    coloured = visible & ((spread >= 24) | ((light >= 135) & (light <= 235)))
    if not coloured.any():
        return "direct_ink"
    thickness = cv2.distanceTransform(coloured.astype(np.uint8), cv2.DIST_L2, 5)
    return "outline_color" if float(thickness.max()) > THICK_PAINT else "direct_ink"


# ------------------------------------------------------------------------------------------------- đường đi của bút
def thin(mask: np.ndarray) -> np.ndarray:
    return cv2.ximgproc.thinning((mask > 0).astype(np.uint8) * 255,
                                 thinningType=cv2.ximgproc.THINNING_GUOHALL) > 0


NEIGHBOURS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
UP, DOWN, HATCH = 0, 1, 2   # trạng thái bút: nhấc, đang vẽ nét, đang tô


def stroke_groups(stroke: np.ndarray, writing: bool) -> tuple[np.ndarray, list[list[int]]]:
    """Nhãn các mảnh nét liền nhau và thứ tự vẽ chúng; vẽ xong một nhóm mới sang nhóm sau.

    Chữ: chia dòng trên → dưới, trong dòng từng chữ cái trái → phải; dấu thanh, dấu chấm, dấu móc (mảnh nhỏ rời) đi
    ngay sau chữ cái của nó — viết xong "XÁC THỰC" mới xuống dòng "HAI LỚP", chữ Á viết A rồi tới dấu sắc. Chữ cái là
    mảnh đủ lớn (từ 30% diện tích mảnh lớn thứ 75 phần trăm trở lên); hai chữ cái cùng dòng khi chồng nhau theo chiều
    dọc ít nhất 40% chiều cao chữ thấp hơn, nên số lớn và dòng chú thích nhỏ bên dưới là hai dòng khác nhau.
    Hình vẽ: thứ tự đọc — các mảnh xếp thành hàng theo chiều dọc, hàng trên trước, trong hàng mảnh bên trái trước
    (dãy ô 8-4-2-1 vẽ từ ô số 8, ổ khoá vẽ quai rồi tới thân)."""
    count, labels, stats, _ = cv2.connectedComponentsWithStats(stroke.astype(np.uint8), connectivity=8)
    ids = [c for c in range(1, count) if stats[c, cv2.CC_STAT_AREA] >= 3]
    if not ids:
        return labels, []
    top = {c: int(stats[c, cv2.CC_STAT_TOP]) for c in ids}
    left = {c: int(stats[c, cv2.CC_STAT_LEFT]) for c in ids}
    bottom = {c: top[c] + int(stats[c, cv2.CC_STAT_HEIGHT]) for c in ids}
    right = {c: left[c] + int(stats[c, cv2.CC_STAT_WIDTH]) for c in ids}

    def rows_of(items: list[int], share: float) -> list[list[int]]:
        rows: list[tuple[int, int, list[int]]] = []
        for c in sorted(items, key=lambda c: (top[c] + bottom[c]) / 2):
            for k, (rt, rb, row) in enumerate(rows):
                overlap = min(bottom[c], rb) - max(top[c], rt)
                if overlap > share * min(bottom[c] - top[c], rb - rt):
                    row.append(c)
                    rows[k] = (min(rt, top[c]), max(rb, bottom[c]), row)
                    break
            else:
                rows.append((top[c], bottom[c], [c]))
        return [sorted(row, key=lambda c: left[c]) for _, _, row in sorted(rows, key=lambda r: r[0])]

    if not writing:
        return labels, [[c] for row in rows_of(ids, 0.35) for c in row]
    areas = sorted(int(stats[c, cv2.CC_STAT_AREA]) for c in ids)
    big_area = areas[min(len(areas) - 1, int(len(areas) * 0.75))]
    letters = [c for c in ids if stats[c, cv2.CC_STAT_AREA] >= 0.3 * big_area]
    marks = [c for c in ids if c not in letters]
    owner: dict[int, list[int]] = {c: [] for c in letters}
    for m in marks:
        def cost(c: int) -> float:
            gap_x = max(0, left[c] - right[m], left[m] - right[c])
            gap_y = max(0, top[c] - bottom[m], top[m] - bottom[c])
            return gap_x * 3 + gap_y
        owner[min(letters, key=cost)].append(m)
    return labels, [[c] + sorted(owner[c], key=lambda m: top[m]) for row in rows_of(letters, 0.4) for c in row]


def walk(skel: np.ndarray, labels: np.ndarray, groups: list[list[int]], writing: bool
         ) -> tuple[np.ndarray, list[tuple[int, int, int, int]]]:
    """Đường bút qua mọi điểm xương, đi hết từng nhóm theo thứ tự `groups`.

    Trả về (toạ độ các điểm xương, đường bút [(y, x, trạng thái, chỉ số điểm xương hoặc -1)]). Trong một nhóm: đi
    thẳng tối đa qua các ngã rẽ, hết đường thì nhấc bút sang điểm chưa vẽ gần nhất (ưu tiên đầu mút)."""
    pts = np.argwhere(skel)
    n = len(pts)
    if not n:
        return pts, []
    index = -np.ones(skel.shape, np.int64)
    index[pts[:, 0], pts[:, 1]] = np.arange(n)
    h, w = skel.shape
    degree = np.zeros(n, np.int8)
    for dy, dx in NEIGHBOURS:
        yy, xx = pts[:, 0] + dy, pts[:, 1] + dx
        ok = (yy >= 0) & (yy < h) & (xx >= 0) & (xx < w)
        degree[ok] += skel[yy[ok], xx[ok]]
    comp = labels[pts[:, 0], pts[:, 1]]
    visited = np.zeros(n, bool)
    path: list[tuple[int, int, int, int]] = []
    listed = {c for g in groups for c in g}
    leftover = [int(c) for c in np.unique(comp) if c not in listed]   # mảnh quá nhỏ để xếp nhóm: vẽ cuối
    for group in groups + ([leftover] if leftover else []):
        members = np.flatnonzero(np.isin(comp, group))
        if not len(members):
            continue
        allowed = np.zeros(n, bool)
        allowed[members] = True
        # bắt đầu ở góc trên-trái của nhóm (chữ: đầu nét trên-trái của chữ cái), ưu tiên đầu mút
        lead = (pts[members, 1] + pts[members, 0] * (0.5 if writing else 0.6)
                - (degree[members] <= 1) * (6.0 if writing else 15.0))
        current = int(members[np.argmin(lead)])
        if path:
            y, x = path[-1][0], path[-1][1]
            path.append((y, x, UP, -1))
            path.append((int(pts[current, 0]), int(pts[current, 1]), UP, -1))
        direction = (0.0, 1.0)
        while True:
            visited[current] = True
            y, x = int(pts[current, 0]), int(pts[current, 1])
            path.append((y, x, DOWN, current))
            best, best_score = -1, -9.0
            for dy, dx in NEIGHBOURS:
                yy, xx = y + dy, x + dx
                if 0 <= yy < h and 0 <= xx < w:
                    j = index[yy, xx]
                    if j >= 0 and allowed[j] and not visited[j]:
                        score = (dy * direction[0] + dx * direction[1]) / math.hypot(dy, dx)
                        if score > best_score:
                            best, best_score = int(j), score
            if best >= 0:
                dy, dx = pts[best, 0] - y, pts[best, 1] - x
                length = math.hypot(dy, dx)
                # giữ quán tính để không rẽ ngang ở ngã ba
                direction = (0.7 * direction[0] + 0.3 * dy / length, 0.7 * direction[1] + 0.3 * dx / length)
                norm = math.hypot(*direction) or 1.0
                direction = (direction[0] / norm, direction[1] / norm)
                current = best
                continue
            rest = members[~visited[members]]
            if not len(rest):
                break
            d = np.hypot(pts[rest, 0] - y, pts[rest, 1] - x) - (degree[rest] <= 1) * 6.0
            nxt = int(rest[np.argmin(d)])
            if math.hypot(pts[nxt, 0] - y, pts[nxt, 1] - x) > 2.5:
                path.append((y, x, UP, -1))
                path.append((int(pts[nxt, 0]), int(pts[nxt, 1]), UP, -1))
            direction = (0.0, 1.0)
            current = nxt
    return pts, path


def timing(path: list[tuple[int, int, int, int]]) -> np.ndarray:
    """Mốc thời gian (giây) của từng điểm trên đường bút, theo nhịp tay người.

    Tay chậm lại ở chỗ ngoặt gắt (tới 0,4 lần) và nhanh trên đoạn thẳng (quy luật 2/3 của chuyển động tay), tăng tốc ở
    đầu nét và hãm lại ở cuối nét, nhấc bút giữa các nét mất LIFT giây mỗi lần nhấc / hạ."""
    n = len(path)
    out = np.zeros(n)
    if n < 2:
        return out
    ys = np.array([p[0] for p in path], np.float64)
    xs = np.array([p[1] for p in path], np.float64)
    state = np.array([p[2] for p in path])
    factor = np.ones(n)
    i = 0
    while i < n:                                   # từng nét liền (các điểm DOWN liên tiếp)
        if state[i] != DOWN:
            i += 1
            continue
        j = i
        while j + 1 < n and state[j + 1] == DOWN:
            j += 1
        py, px = ys[i:j + 1], xs[i:j + 1]
        seg = np.hypot(np.diff(py), np.diff(px))
        arc = np.concatenate([[0.0], np.cumsum(seg)])
        k = np.arange(len(py))
        a, b = np.clip(k - 5, 0, len(py) - 1), np.clip(k + 5, 0, len(py) - 1)
        v1 = np.stack([py - py[a], px - px[a]], 1)
        v2 = np.stack([py[b] - py, px[b] - px], 1)
        cos = (v1 * v2).sum(1) / np.maximum(1e-6, np.hypot(*v1.T) * np.hypot(*v2.T))
        bend = np.arccos(np.clip(cos, -1, 1))
        curve = 1 - 0.6 * np.clip(bend / 1.6, 0, 1)
        ramp = np.clip(0.35 + 0.65 * np.minimum(arc, arc[-1] - arc) / 18.0, 0.35, 1.0)
        factor[i:j + 1] = np.maximum(0.25, curve * ramp)
        i = j + 1
    for i in range(1, n):
        step = math.hypot(ys[i] - ys[i - 1], xs[i] - xs[i - 1])
        if state[i - 1] == DOWN and state[i] == DOWN:
            out[i] = out[i - 1] + step / (PEN_SPEED * factor[i])
        elif state[i - 1] == UP and state[i] == UP:
            # nhấc bút sang nét khác: giữa hai chữ cái chỉ ~0,03 giây, sang hình ở xa thì lâu hơn
            out[i] = out[i - 1] + LIFT + min(0.06, step / 1500.0) + step / AIR_SPEED
        else:                                      # lúc nhấc / hạ bút: thời gian đã tính trong bước bay
            out[i] = out[i - 1]
    return out


# --------------------------------------------------------------------------------------------------- dựng kế hoạch
class Plan:
    """Mỗi điểm ảnh có một thời điểm hiện ra; bút có một đường đi theo thời gian."""

    def __init__(self, rgba: np.ndarray, mode: str, order: str = "auto"):
        self.rgba = rgba
        h, w = rgba.shape[:2]
        alpha = rgba[..., 3]
        visible = alpha > 10
        ys, xs = np.nonzero(visible)
        if not len(ys):
            raise ValueError("lớp hình trống")
        pad = 4
        self.box = (max(0, ys.min() - pad), min(h, ys.max() + pad + 1), max(0, xs.min() - pad), min(w, xs.max() + pad + 1))
        y0, y1, x0, x1 = self.box
        crop = rgba[y0:y1, x0:x1]
        vis = crop[..., 3] > 10
        rgb = crop[..., :3].astype(np.float32)
        if mode == "auto":
            mode = automatic_mode(rgb, vis)
        self.mode = mode
        sketch_ink = None
        if mode == "outline_color":
            ink = (luminance(rgb) < 125) & vis
            other = vis & ~ink
            stroke = ink.copy()
            count, labels, stats, _ = cv2.connectedComponentsWithStats(other.astype(np.uint8), connectivity=8)
            dist = cv2.distanceTransform(other.astype(np.uint8), cv2.DIST_L2, 5)
            for c in range(1, count):
                part = labels == c
                if dist[part].max() <= THIN:          # mảnh: mũi tên màu, chữ màu → vẽ như nét
                    stroke |= part
            fill = vis & ~stroke
        elif mode == "direct_ink":
            # A thin arrow, handwritten word, or monochrome icon is one pen
            # operation. Reveal original coloured pixels from its skeleton;
            # do not draw a grey outline and then revisit it with a fill pass.
            stroke = vis.copy()
            fill = np.zeros_like(vis)
            sketch_ink = stroke
        else:  # direct_color: rich artwork, sketch edges then reveal colour
            gray = cv2.cvtColor(crop[..., :3], cv2.COLOR_RGB2GRAY)
            edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 60, 140)
            edges = cv2.dilate(edges, np.ones((2, 2), np.uint8)) > 0
            stroke = edges & vis
            fill = vis.copy()
            sketch_ink = stroke
        self.stroke_mask, self.fill_mask, self.sketch_ink = stroke, fill, sketch_ink

        # ---- nét: thời điểm của từng điểm ảnh = thời điểm bút qua điểm xương gần nhất
        self.pix_time = np.full(vis.shape, np.inf, np.float64)
        skel = thin(stroke) if stroke.any() else np.zeros_like(stroke)
        ch, cw = vis.shape
        writing = order == "writing" or (order == "auto" and ch < 200 and cw > 2.2 * ch)   # một dòng chữ
        comp_labels, groups = stroke_groups(stroke, writing)
        pts, path = walk(skel, comp_labels, groups, writing)
        path_t = timing(path)
        times = np.zeros(len(pts))
        for (_, _, _, idx), t in zip(path, path_t):
            if idx >= 0:
                times[idx] = t
        if len(pts):
            src = (~skel).astype(np.uint8)
            _, labels = cv2.distanceTransformWithLabels(src, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
            self.pix_time[stroke] = times[labels[stroke] - 1]
        stroke_end = float(path_t[-1]) if len(path) else 0.0
        self.stroke_time = np.where(stroke, self.pix_time, np.inf) if mode == "direct_color" else None

        # ---- tô màu: từng mảng quét trái → phải, bút zig-zag theo vệt quét
        pen = [(y + y0, x + x0, state) for y, x, state, _ in path]
        pen_t = list(path_t) if path else []
        clock = stroke_end + (0.12 if path else 0.0)
        fill_time = np.full(vis.shape, np.inf, np.float64)
        regions = fill.astype(np.uint8)
        if mode == "direct_color":
            regions = cv2.dilate(regions, np.ones((9, 9), np.uint8))
        count, labels, stats, _ = cv2.connectedComponentsWithStats(regions, connectivity=8)
        order = sorted(range(1, count), key=lambda c: (stats[c, cv2.CC_STAT_LEFT] + stats[c, cv2.CC_STAT_TOP] * 0.5))
        for c in order:
            part = (labels == c) & fill
            area = int(part.sum())
            if area < 30:
                fill_time[part] = clock
                continue
            if mode == "outline_color" and np.percentile(rgb[part].min(axis=1), 10) >= 238:
                # mảng trắng / gần màu giấy (lòng ô số, màn hình laptop): không ai tô màu trắng — hiện ra ngay khi
                # viền bao quanh vẽ xong, bàn tay không phải quay lại từng ô
                ring = cv2.dilate(part.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
                edge_t = self.pix_time[ring & stroke]
                fill_time[part] = float(edge_t[np.isfinite(edge_t)].max()) if np.isfinite(edge_t).any() else 0.0
                continue
            cx0, cy0 = stats[c, cv2.CC_STAT_LEFT], stats[c, cv2.CC_STAT_TOP]
            cw, ch = stats[c, cv2.CC_STAT_WIDTH], stats[c, cv2.CC_STAT_HEIGHT]
            span = float(np.clip(math.sqrt(area) / 1100.0, 0.16, 0.75))
            if mode == "direct_color":
                span = float(np.clip(math.sqrt(area) / 900.0, 0.5, 1.6))
            yy, xx = np.nonzero(part)
            fill_time[yy, xx] = clock + (xx - cx0) / max(1, cw - 1) * span
            # đường zig-zag: mỗi cột cách nhau ~34 px, bút chạy giữa mép trên và mép dưới của mảng tại cột đó;
            # cột k có cùng thời điểm với vệt quét đi qua nó (fill_time ở trên)
            columns = max(2, int(cw / 34) + 1)
            half = span / (columns - 1) / 2
            if pen:
                pen.append((pen[-1][0], pen[-1][1], UP)); pen_t.append(pen_t[-1] + 0.02)
            for k in range(columns):
                cx = cx0 + (cw - 1) * k / (columns - 1)
                rows = np.flatnonzero(part[:, int(round(cx))])
                top, bottom = (rows.min(), rows.max()) if len(rows) else (cy0, cy0 + ch - 1)
                y_first, y_second = (top, bottom) if k % 2 == 0 else (bottom, top)
                t_col = clock + k / (columns - 1) * span
                pen.append((int(y_first + y0), int(cx + x0), HATCH)); pen_t.append(t_col)
                pen.append((int(y_second + y0), int(cx + x0), HATCH)); pen_t.append(t_col + half)
            clock = pen_t[-1] + 0.08
        self.fill_time = fill_time
        self.total = max(clock, stroke_end, 0.2)
        self.pen = pen
        self.pen_t = np.array(pen_t) if pen_t else np.zeros(0)

    def natural(self) -> float:
        return self.total

    def pen_at(self, t: float) -> tuple[float, float, int]:
        """(y, x, trạng thái bút UP / DOWN / HATCH) ở thời điểm t."""
        if not len(self.pen):
            y0, y1, x0, x1 = self.box
            return (y0 + y1) / 2, (x0 + x1) / 2, UP
        i = int(np.searchsorted(self.pen_t, t, side="right"))
        if i <= 0:
            y, x, d = self.pen[0]
            return float(y), float(x), d
        if i >= len(self.pen):
            y, x, _ = self.pen[-1]
            return float(y), float(x), UP
        (ya, xa, da), (yb, xb, db) = self.pen[i - 1], self.pen[i]
        ta, tb = self.pen_t[i - 1], self.pen_t[i]
        k = 0.0 if tb <= ta else (t - ta) / (tb - ta)
        return ya + (yb - ya) * k, xa + (xb - xa) * k, (da if da == db else UP)

    def frame(self, t: float) -> np.ndarray:
        """RGBA toàn khung của lớp này ở thời điểm t (giây, theo nhịp tự nhiên)."""
        h, w = self.rgba.shape[:2]
        out = np.zeros((h, w, 4), np.uint8)
        y0, y1, x0, x1 = self.box
        crop = self.rgba[y0:y1, x0:x1]
        if self.mode == "direct_ink":
            shown = self.pix_time <= t
            part = np.zeros_like(crop)
            part[shown] = crop[shown]
        elif self.mode == "direct_color":
            shown = self.fill_time <= t
            sketch = (self.stroke_time <= t) & ~shown
            part = np.zeros_like(crop)
            part[shown] = crop[shown]
            part[sketch] = (70, 70, 74, 255)
        else:
            shown = (self.pix_time <= t) | (self.fill_time <= t)
            part = np.zeros_like(crop)
            part[shown] = crop[shown]
        out[y0:y1, x0:x1] = part
        return out


# ------------------------------------------------------------------------------------------------------- xuất khung
def schedule(plan: Plan, seconds: float, natural: bool, fps: int) -> tuple[int, float, float]:
    """(số khung, thời lượng thật, hệ số thời gian tự nhiên / giây clip)."""
    want = plan.natural()
    if natural:
        # tốc độ tay người, co giãn trong khoảng 0,75–1,7 lần để lấp phần lớn khung giờ của lớp: vẽ xong quá sớm thì
        # tay phải đứng chờ lâu, vẽ chậm đều cả khung thì nét bò như phim quay chậm
        target = min(max(seconds * 0.85, want * 0.75), want * 1.7)
        duration = min(seconds, max(0.5, target))
    else:
        duration = seconds
    frames = max(2, int(round(duration * fps)))
    return frames, frames / fps, want / (frames / fps)


def write_frames(plan: Plan, frames: int, scale: float, fps: int, frames_dir: Path, pen_json: Path | None) -> None:
    frames_dir.mkdir(parents=True, exist_ok=True)
    h, w = plan.rgba.shape[:2]
    pen = []
    for i in range(frames):
        t = (i + 1) / fps * scale if i < frames - 1 else plan.total + 1
        rgba = plan.frame(t)
        cv2.imwrite(str(frames_dir / f"frame-{i:05d}.png"), cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA),
                    [cv2.IMWRITE_PNG_COMPRESSION, 1])
        y, x, state = plan.pen_at(min(t, plan.total))
        pen.append([round(x / w, 5), round(y / h, 5), int(state)])   # 0 nhấc bút, 1 vẽ nét, 2 tô màu
    if pen_json:
        pen_json.write_text(json.dumps({"fps": fps, "frames": frames, "duration": round(frames / fps, 4),
                                        "points": pen}), encoding="utf-8")


def write_video(plan: Plan, frames: int, scale: float, fps: int, output: Path, hand_path: Path) -> None:
    """Clip MP4 nền giấy, có bàn tay (giao diện cũ của Whiteboard Lab)."""
    h, w = plan.rgba.shape[:2]
    paper = np.empty((h, w, 3), np.float32)
    paper[:] = PAPER_RGB
    hand = np.asarray(Image.open(hand_path).convert("RGBA")).astype(np.float32) if hand_path.exists() else None
    meta = json.loads(hand_path.with_suffix(".json").read_text(encoding="utf-8")) if hand is not None else {}
    tip = meta.get("tip", [0, 0])
    output.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
                             "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "14",
                             "-pix_fmt", "yuv420p", str(output)], stdin=subprocess.PIPE)
    for i in range(frames):
        t = (i + 1) / fps * scale if i < frames - 1 else plan.total + 1
        rgba = plan.frame(t).astype(np.float32)
        a = rgba[..., 3:4] / 255.0
        img = paper * (1 - a) + rgba[..., :3] * a
        if hand is not None and i < frames - 1:
            y, x, state = plan.pen_at(min(t, plan.total))
            lift = 0 if state else 10
            overlay(img, hand, int(round(x - tip[0])), int(round(y - tip[1] - lift)))
        proc.stdin.write(np.clip(img, 0, 255).astype(np.uint8).tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg không ghi được clip whiteboard")


def overlay(img: np.ndarray, sprite: np.ndarray, left: int, top: int) -> None:
    h, w = img.shape[:2]
    sh, sw = sprite.shape[:2]
    x0, y0, x1, y1 = max(0, left), max(0, top), min(w, left + sw), min(h, top + sh)
    if x0 >= x1 or y0 >= y1:
        return
    part = sprite[y0 - top:y1 - top, x0 - left:x1 - left]
    a = part[..., 3:4] / 255.0
    img[y0:y1, x0:x1] = img[y0:y1, x0:x1] * (1 - a) + part[..., :3] * a


# --------------------------------------------------------------------------------------------------- tách vật thể
def split_objects(image: Path, out_dir: Path, limit: int = 6) -> dict:
    """Split a clean board into a few complete, spatially coherent objects.

    The bridge scales with the canvas, preserves meaningful foreground pixels,
    and merges excess groups with their closest neighbour instead of silently
    dropping small labels or accents.
    """
    rgba = load_rgba(image)
    h, w = rgba.shape[:2]
    vis = (rgba[..., 3] > 10).astype(np.uint8)
    bridge = max(5, min(35, round(min(h, w) * 0.025)))
    if bridge % 2 == 0:
        bridge += 1
    grown = cv2.dilate(vis, np.ones((bridge, bridge), np.uint8))
    count, labels, _stats, _ = cv2.connectedComponentsWithStats(grown, connectivity=8)
    minimum = max(16, int(vis.sum() * 0.002))
    parts = []
    for component in range(1, count):
        mask = (labels == component) & (vis > 0)
        if int(mask.sum()) < minimum:
            continue
        ys, xs = np.where(mask)
        parts.append({"mask": mask, "pixels": int(mask.sum()),
                      "box": (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)})
    out_dir.mkdir(parents=True, exist_ok=True)
    if not parts or sum(part["pixels"] for part in parts) < 0.80 * int(vis.sum()):
        return {"layers": [], "fallback": True}

    def gap(a, b):
        ax0, ay0, ax1, ay1 = a["box"]; bx0, by0, bx1, by1 = b["box"]
        dx, dy = max(0, ax0 - bx1, bx0 - ax1), max(0, ay0 - by1, by0 - ay1)
        return dx * dx + dy * dy

    # Dots, diacritics, phone buttons and chart markers are often separate
    # connected components even though their bounding box sits inside the
    # main icon.  Keep them with that icon before applying the general limit.
    changed = True
    while changed and len(parts) > 1:
        changed = False
        largest = max(part["pixels"] for part in parts)
        for small in sorted(range(len(parts)), key=lambda i: parts[i]["pixels"]):
            if parts[small]["pixels"] > largest * 0.08:
                break
            other = min((i for i in range(len(parts)) if i != small), key=lambda i: gap(parts[small], parts[i]))
            if gap(parts[small], parts[other]) > (bridge * 3) ** 2:
                continue
            merged = parts[small]["mask"] | parts[other]["mask"]
            ys, xs = np.where(merged)
            parts[other] = {"mask": merged, "pixels": int(merged.sum()),
                            "box": (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)}
            parts.pop(small)
            changed = True
            break

    while len(parts) > limit:
        small = min(range(len(parts)), key=lambda i: parts[i]["pixels"])
        other = min((i for i in range(len(parts)) if i != small), key=lambda i: gap(parts[small], parts[i]))
        merged = parts[small]["mask"] | parts[other]["mask"]
        ys, xs = np.where(merged)
        parts[other] = {"mask": merged, "pixels": int(merged.sum()),
                        "box": (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)}
        parts.pop(small)
    parts.sort(key=lambda part: (part["box"][1] // max(1, h // 12), part["box"][0]))

    layers = []
    for number, part in enumerate(parts, 1):
        mask = part["mask"]
        layer = np.zeros_like(rgba)
        layer[mask] = rgba[mask]
        name = f"layer-{number:02d}.png"
        Image.fromarray(layer, "RGBA").save(out_dir / name)
        ys, xs = np.nonzero(mask)
        layers.append({"file": name, "weight": float(math.sqrt(mask.sum())),
                       "bbox": {"x": round(xs.min() / w, 5), "y": round(ys.min() / h, 5),
                                "w": round((xs.max() - xs.min()) / w, 5), "h": round((ys.max() - ys.min()) / h, 5)}})
    return {"layers": layers, "fallback": False}


def main() -> None:
    ap = argparse.ArgumentParser(description="Whiteboard Lab: dựng clip bàn tay vẽ từ một lớp hình")
    ap.add_argument("--image", required=True, type=Path)
    ap.add_argument("--output", type=Path, help="clip MP4 nền giấy có bàn tay")
    ap.add_argument("--frames-dir", type=Path, help="khung PNG trong suốt chỉ có nét vẽ")
    ap.add_argument("--pen-json", type=Path, help="vị trí đầu bút từng khung")
    ap.add_argument("--duration", type=float, default=2.0)
    ap.add_argument("--natural", action="store_true", help="vẽ theo tốc độ tay, tối đa --duration giây")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--mode", default="auto", choices=["auto", "outline_color", "direct_color", "direct_ink"])
    ap.add_argument("--order", default="auto", choices=["auto", "nearest", "writing"],
                    help="thứ tự nét: writing = chữ từ trái sang phải, nearest = nét gần nhất (hình vẽ)")
    ap.add_argument("--split-objects", type=Path)
    ap.add_argument("--estimate", action="store_true",
                    help="chỉ đo độ dài thao tác vẽ để Factory chia thời lượng giữa các layer")
    ap.add_argument("--hand", type=Path, default=HAND)
    a = ap.parse_args()
    if a.split_objects:
        print(json.dumps(split_objects(a.image, a.split_objects)))
        return
    if a.estimate:
        plan = Plan(load_rgba(a.image), a.mode, a.order)
        # Use the Lab's own pen route.  This is more meaningful than an
        # object's bounding box: small handwriting may contain more pen work
        # than a large, sparse icon.
        print(json.dumps({"cost": round(max(0.45, plan.natural()), 4),
                          "pen_points": len(plan.pen), "mode": plan.mode}))
        return
    if not a.output and not a.frames_dir:
        ap.error("cần --output hoặc --frames-dir")
    plan = Plan(load_rgba(a.image), a.mode, a.order)
    frames, duration, scale = schedule(plan, max(0.1, a.duration), a.natural, a.fps)
    if a.frames_dir:
        shutil.rmtree(a.frames_dir, ignore_errors=True)
        write_frames(plan, frames, scale, a.fps, a.frames_dir, a.pen_json)
    if a.output:
        write_video(plan, frames, scale, a.fps, a.output, a.hand)
    print(json.dumps({"frames": frames, "duration": round(duration, 3), "fps": a.fps, "mode": plan.mode,
                      "natural": round(plan.natural(), 3)}))


if __name__ == "__main__":
    main()
