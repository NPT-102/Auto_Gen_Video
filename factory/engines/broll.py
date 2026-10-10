"""Stock khớp lời: mỗi cảnh tự tìm clip Pexels theo từ khoá của chính nó và chiếm đúng khoảng thời gian cảnh được đọc.

MoneyPrinterTurbo tìm theo vài từ khoá chung rồi xếp clip ngẫu nhiên (chế độ "khớp kịch bản" của nó chỉ xoay vòng
từ khoá), nên clip cây cầu có thể hiện lúc đang nói chuyện đồng nghiệp. Ở đây cảnh nào có clip của cảnh đó,
đổi clip khoảng mỗi 3 giây. Từ khoá lấy ở trường "stock" của từng cảnh; kịch bản không có thì chia đều stock_terms
theo thứ tự lời đọc. Chữ trên hình (nhãn, con số, ý chính) hiện đúng lúc được đọc; phụ đề karaoke đốt bằng libass.
"""

import concurrent.futures as cf
import hashlib
import json
import shutil
import threading
import time
from pathlib import Path

import httpx

from ..beats import _queries as beat_queries, plan as beat_plan
from ..captions import esc, karaoke_ass
from ..config import CACHE_DIR, ENGINES_DIR, pexels_api_key
from ..narration import attach_punctuation, build_audio, build_timeline, synthesize_spec
from ..spec import Spec
from .base import Engine, EngineError, Log, run

API = "https://api.pexels.com/v1/videos/search"
FPS = 30
CUT = 3.0                       # giây mỗi clip (nhịp video kiến thức trên TikTok: hình đổi mỗi 1,5–3 giây)
STOCK = CACHE_DIR / "stock"     # kết quả tìm kiếm + clip đã tải, dùng lại giữa các video
FONTS = ENGINES_DIR / "hyperframes-academic" / "fonts"


def scene_terms(spec: Spec) -> list[list[str]]:
    """Từ khoá của từng cảnh: "stock" riêng trước, rồi stock_terms chung làm dự phòng khi thiếu clip."""
    shared = [t.strip() for t in spec.stock_terms if t.strip()]
    n = len(spec.scenes)
    out = []
    for i, sc in enumerate(spec.scenes):
        own = [str(t).strip() for t in (sc.model_extra or {}).get("stock") or [] if str(t).strip()]
        if not own and shared:
            own = [shared[i * len(shared) // n]]
        out.append(own + [t for t in shared if t not in own])
    if not any(out):
        out = [[spec.title]] * n     # không có từ khoá nào: tìm theo tiêu đề (tiếng Việt, locale vi-VN)
    return out


def search(term: str, key: str, orientation: str = "portrait") -> list[dict]:
    f = STOCK / "search" / f"{hashlib.sha1(f'{orientation}|{term.lower()}'.encode()).hexdigest()[:16]}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    params = {"query": term, "per_page": 30, "orientation": orientation}
    if not term.isascii():
        params["locale"] = "vi-VN"   # tìm bằng tiếng Việt mà không kèm locale thì Pexels trả kết quả lạc đề
    for attempt in range(3):
        try:
            r = httpx.get(API, headers={"Authorization": key}, params=params, timeout=30)
        except httpx.HTTPError:
            r = None
        if r is not None and r.status_code == 200:
            break
        if r is not None and r.status_code < 500 and r.status_code != 429:
            raise EngineError(f"Pexels trả lỗi HTTP {r.status_code} khi tìm '{term}'")
        time.sleep(2 * (attempt + 1))
    else:
        return []   # Pexels lỗi máy chủ (500 với vài từ khoá): bỏ qua từ khoá này, không ghi cache, dùng từ khoá dự phòng
    clips = []
    for v in r.json().get("videos", []):
        files = [x for x in v.get("video_files", []) if x.get("width") and x.get("height")
                 and (x["height"] > x["width"]) == (orientation == "portrait")]
        if not files or v.get("duration", 0) < 3:
            continue
        side = (lambda x: x["width"]) if orientation == "portrait" else (lambda x: x["height"])
        best = min(files, key=lambda x: (abs(side(x) - 1080), -side(x)))
        clips.append({"id": v["id"], "url": best["link"], "duration": v["duration"], "page": v.get("url", ""),
                      "portrait": orientation == "portrait"})
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(clips), encoding="utf-8")
    return clips


def download(clip: dict) -> Path:
    dst = STOCK / "videos" / f"pexels-{clip['id']}.mp4"
    if dst.exists() and dst.stat().st_size > 0:
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f"{dst.name}.{threading.get_ident()}.part")   # tải song song không đè nhau
    for attempt in range(3):
        try:
            with httpx.stream("GET", clip["url"], timeout=60, follow_redirects=True) as r:
                r.raise_for_status()
                with open(tmp, "wb") as fh:
                    for chunk in r.iter_bytes(1 << 20):
                        fh.write(chunk)
            tmp.replace(dst)
            return dst
        except (httpx.HTTPError, OSError):
            if attempt == 2:
                raise
    return dst


def plan(spec: Spec, data: dict, key: str, log: Log) -> list[dict]:
    """Chia lời đọc thành các đoạn ~CUT giây (tính theo khung hình để tiếng và hình không lệch) và chọn clip.

    Từ 01/10/2026 mỗi câu (beat của factory/beats.py: đổi sớm hơn lời BEAT_LEAD giây) tìm clip theo từ khoá riêng của
    câu — cùng từ khoá với ảnh theo câu của các engine khác; cảnh sơ đồ và lúc thiếu clip thì dùng từ khoá của cảnh."""
    used: set[int] = set()
    cuts = []
    sentences = beat_plan(data)
    queries = beat_queries(spec, sentences, log) if sentences and (spec.model_extra or {}).get("images") is not False else []
    parts: dict[int, list[tuple[float, float, str | None]]] = {}
    for b, q in zip(sentences, queries):
        parts.setdefault(b["scene"], []).append((b["t0"], b["t1"], q))
    for i, (terms, s) in enumerate(zip(scene_terms(spec), data["scenes"])):
        for t0, t1, query in parts.get(i) or [(s["start"], s["end"], None)]:
            f0, f1 = round(t0 * FPS), round(min(t1, s["end"]) * FPS)
            k = max(1, round((f1 - f0) / FPS / CUT))
            pool: dict[int, dict] = {}
            for term in ([query] if query else []) + terms:
                pool.update((c["id"], c) for c in search(term, key) if c["id"] not in pool)
                if sum(cid not in used for cid in pool) >= k:
                    break
            if len(pool) < k:   # ít clip dọc: lấy thêm clip ngang, cắt giữa khung
                pool.update((c["id"], c) for c in search(query or terms[0], key, "landscape") if c["id"] not in pool)
            if not pool:
                raise EngineError(f"cảnh {i + 1}: Pexels không có clip cho {([query] if query else []) + terms[:2]}")
            fresh = [c for c in pool.values() if c["id"] not in used] or list(pool.values())
            log(f"cảnh {i + 1} @{t0:.1f}s: '{query or terms[0]}' → {k} clip")
            bounds = [f0 + (f1 - f0) * j // k for j in range(k + 1)]
            for j in range(k):
                clip = fresh[j % len(fresh)]
                used.add(clip["id"])
                n = bounds[j + 1] - bounds[j]
                offset = 0.4 + (j // len(fresh)) * (n / FPS)          # dùng lại clip thì lấy đoạn khác của nó
                offset = offset if offset + n / FPS < clip["duration"] else 0.0
                cuts.append({"clip": clip, "frames": n, "offset": offset, "scene": i})
    return cuts


def overlays(spec: Spec, data: dict) -> list[tuple[float, float, str, str]]:
    """Chữ trên hình: nhãn cảnh (trên cùng) + ý chính hiện đúng lúc được đọc (con số, ý, nút sơ đồ, đáp án)."""
    out = []
    for sc, s in zip(spec.scenes, data["scenes"]):
        x, a, b = sc.model_dump(), s["start"], s["end"]
        label = x.get("kicker") or x.get("tag") or x.get("label") or ""
        out.append((a, b, "Kicker", esc(label.upper())))
        beats: list[tuple[float, str]] = []
        if sc.type == "title":
            beats = [(a, esc(" ".join(tok[0] for tok in x.get("headline", []))))]
        elif sc.type == "stat":
            beats = [(st.get("t", a), f"{esc(st['value'])}\\N{{\\fs44}}{esc(st.get('label', ''))}") for st in s.get("stats", [])]
        elif sc.type == "bullets":
            beats = [(it.get("t", a), esc(it["text"])) for it in s.get("items", [])]
        elif sc.type == "compare":
            beats = [(s[k].get("t", a), esc(s[k]["title"])) for k in ("left", "right") if isinstance(s.get(k), dict)]
        elif sc.type == "flow":
            names = {n["id"]: n.get("label", "") for n in x.get("nodes", [])}
            beats = [(ev["t"], esc(" · ".join(names[i] for i in ev.get("show", []) if i in names)))
                     for ev in s.get("events", []) if ev.get("t") is not None]
        elif sc.type == "tip":
            beats = [(a, "{\\fs52}" + esc(x["question"])), (s.get("answer_t", b), esc(x["answer"]))]
        elif sc.type == "next":
            beats = [(a, esc(x["title"]))]
        beats = sorted((max(a, t), txt) for t, txt in beats if txt)
        for k, (t, txt) in enumerate(beats):
            out.append((t, beats[k + 1][0] if k + 1 < len(beats) else b, "Hook", txt))
    return out


class StockBRoll(Engine):
    key = "broll"
    label = "Stock khớp lời"
    style = "Clip Pexels đổi theo từng câu, chữ hiện đúng lúc đọc, phụ đề karaoke"

    def check(self):
        if not pexels_api_key():
            return False, "chưa có key Pexels (PEXELS_API_KEY trong .env)"
        return True, ""

    def render(self, spec: Spec, workdir: Path, log: Log) -> Path:
        key = pexels_api_key()
        data, parts = build_timeline(spec, log)
        log(f"{data['duration']:.1f} giây, {len(data['scenes'])} cảnh")
        build_audio(parts, workdir / "narration.wav", data, spec.title)

        cuts = plan(spec, data, key, log)
        clips = {c["clip"]["id"]: c["clip"] for c in cuts}
        log(f"tải {len(clips)} clip Pexels (dùng lại clip đã tải ở video trước)")
        with cf.ThreadPoolExecutor(6) as pool:
            files = dict(zip(clips, pool.map(download, clips.values())))

        seg_dir = workdir / "segments"
        seg_dir.mkdir(exist_ok=True)
        log_file = workdir / "log.txt"

        def encode(item):
            j, c = item
            crop = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
            out = seg_dir / f"{j:03d}.mp4"
            run(["ffmpeg", "-v", "error", "-y", "-stream_loop", "-1", "-ss", f"{c['offset']:.2f}", "-i", str(files[c['clip']['id']]),
                 "-frames:v", str(c["frames"]), "-vf", f"{crop},setsar=1,fps={FPS},format=yuv420p", "-an",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS), str(out)], cwd=workdir, log_file=log_file)
            return out

        log(f"cắt {len(cuts)} đoạn theo thời lượng từng cảnh")
        with cf.ThreadPoolExecutor(4) as pool:
            segs = list(pool.map(encode, enumerate(cuts)))
        (workdir / "segments.txt").write_text("".join(f"file 'segments/{p.name}'\n" for p in segs), encoding="utf-8")

        words = []
        for i, (sc, s) in enumerate(zip(spec.scenes, data["scenes"])):
            _, ws, _ = synthesize_spec(sc.say, spec)
            attach_punctuation(sc.say, ws)
            words += [dict(w, start=w["start"] + s["audio_at"], end=w["end"] + s["audio_at"], scene=i) for w in ws]
        (workdir / "captions.ass").write_text(karaoke_ass(words, overlays(spec, data)), encoding="utf-8")
        shutil.copytree(FONTS, workdir / "fonts", dirs_exist_ok=True)
        (workdir / "sources.txt").write_text(
            "Video từ Pexels (miễn phí, không bắt buộc ghi nguồn):\n" + "\n".join(c["page"] for c in clips.values()), encoding="utf-8")

        log("ghép clip, giọng đọc, chữ và phụ đề")
        run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", "segments.txt", "-i", "narration.wav",
             "-vf", "subtitles=captions.ass:fontsdir=fonts", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", "video.mp4"],
            cwd=workdir, log_file=log_file)
        shutil.rmtree(seg_dir, ignore_errors=True)
        (workdir / "narration.wav").unlink(missing_ok=True)
        return workdir / "video.mp4"
