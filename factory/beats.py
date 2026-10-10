"""Ảnh minh hoạ theo từng câu kể ("beat") cho mọi engine dựng hình (HyperFrames, Remotion, AI-auto, Pixelle).

Người xem góp ý hai engine này ít hình và hình hiện chậm so với lời kể: mỗi câu giờ có một ảnh nền riêng, đổi đúng
lúc câu bắt đầu (sớm hơn lời BEAT_LEAD giây), mờ chuyển và zoom chậm. Cảnh sơ đồ không có ảnh để sơ đồ vẫn dễ đọc;
đặt "images": false trong kịch bản để tắt hẳn (vd. series AWS nhiều sơ đồ).

Nguồn ảnh (IMAGE_SOURCE trong .env):
- pexels (mặc định): ảnh chụp thật, miễn phí — Gemini đặt từ khoá tìm ảnh cho từng câu trong một lần gọi.
- comfyui: vẽ bằng ComfyUI chạy trên GPU của máy (SDXL-Lightning 4 bước, ~3 giây/ảnh, miễn phí) — bật bằng
  python3 chay-comfyui.py; Gemini viết mô tả cảnh cho từng câu.
- gemini: vẽ bằng Gemini (cần bật thanh toán: gói miễn phí không có hạn mức vẽ ảnh).
Vẽ lỗi (ComfyUI chưa bật, hết hạn mức…) thì quay về Pexels theo từ khoá clip của cảnh.
"""

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import httpx

from .config import CACHE_DIR, _read_dotenv, gemini_api_key, pexels_api_key, stock_api_key, stock_provider
from . import pixabay
from .spec import Spec

BEAT_LEAD = 0.35        # ảnh đổi sớm hơn câu được đọc
MIN_BEAT = 2.4          # câu ngắn hơn thì dùng chung ảnh với câu trước
SKIP = {"diagram", "flow"}
CACHE = CACHE_DIR / "beats"
PHOTOS = CACHE_DIR / "stock" / "photos"
_lock = threading.Lock()

QUERY_PROMPT = """You pick background photos for a Vietnamese TikTok video titled "{title}".
For each numbered sentence, write ONE English search query (2-5 words) for a REAL stock photo that shows what the sentence
is about — concrete people, places, objects or actions a camera can shoot, matching the emotion. Never abstract words,
never text, charts or diagrams. Keep one consistent visual mood across the video: {mood}.
Sentences:
{numbered}
Return ONLY JSON: {{"queries": ["...", "..."]}} with exactly {n} items, in the same order."""

AI_PROMPT = """You write prompts for an AI image model (SDXL) to illustrate a Vietnamese TikTok video titled "{title}".
For each numbered sentence, write ONE English prompt (12-25 words) describing a realistic photo of what THAT sentence is
about: concrete subject, place, action, emotion and lighting. Every prompt must show a different subject taken from its
own sentence — never repeat the same scene for different sentences. {note} Never text, letters, logos, charts or
diagrams. Keep colour and light consistent across the video ({mood}); this is about style only, not the subject.
Sentences:
{numbered}
Return ONLY JSON: {{"queries": ["...", "..."]}} with exactly {n} items, in the same order."""
# Ghi chú mặc định cho mô tả cảnh; kịch bản đặt "image_note" để đổi (vd. chỉ thiên nhiên, không người).
AI_NOTE = "People are young Vietnamese unless the sentence is about a specific foreign person, experiment or place."

AI_STYLE = "Cinematic vertical photo, soft natural light, shallow depth of field, realistic, no text, no letters, no watermark."
COMFY_STYLE = "cinematic vertical photo, natural light, shallow depth of field, realistic, 35mm film, no text"
COMFY_CKPT = "sdxl_lightning_4step.safetensors"
_comfy_lock = threading.Lock()   # ComfyUI vẽ lần lượt; engine chạy song song xin cùng ảnh thì chờ rồi dùng cache


def _source(spec: Spec | None = None) -> str:
    """Nguồn ảnh: "image_source" của kịch bản, rồi IMAGE_SOURCE (biến môi trường / .env), mặc định pexels."""
    own = (spec.model_extra or {}).get("image_source") if spec else None
    return (own or os.environ.get("IMAGE_SOURCE") or _read_dotenv().get("IMAGE_SOURCE") or stock_provider()).strip().lower()


SENTENCE_END = (".", "!", "?", "…")
PHRASE_END = SENTENCE_END + (",", ";", ":")   # băm theo vế câu: mỗi vế một cảnh


def _sentences(words: list[dict], ends: tuple[str, ...] = SENTENCE_END) -> list[list[dict]]:
    out, cur = [], []
    for w in words:
        cur.append(w)
        if w["display"].rstrip("”\"')").endswith(ends):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def plan(data: dict, skip: set[str] = SKIP, min_beat: float = MIN_BEAT, ends: tuple[str, ...] = SENTENCE_END) -> list[dict]:
    """Chia lời đọc thành các beat {scene, t0, t1, text}: mỗi câu (hoặc mỗi vế, nếu `ends` có dấu phẩy) một ảnh;
    đoạn ngắn hơn min_beat gộp với đoạn trước."""
    beats: list[dict] = []
    for i, s in enumerate(data["scenes"]):
        if s["type"] in skip:
            continue
        words = [w for w in data["words"] if s["start"] <= w["start"] < s["end"]]
        for k, sent in enumerate(_sentences(words, ends)):
            text = " ".join(w["display"] for w in sent)
            short = sent[-1]["end"] - sent[0]["start"] < min_beat
            if k and short and beats and beats[-1]["scene"] == i:
                beats[-1]["text"] += " " + text
                continue
            t0 = s["start"] if k == 0 else max(s["start"], sent[0]["start"] - BEAT_LEAD)
            beats.append({"scene": i, "t0": t0, "t1": s["end"], "text": text})
    for a, b in zip(beats, beats[1:]):
        if a["scene"] == b["scene"] or b["t0"] - a["t1"] < 1.0:   # liền nhau: ảnh sau thay ảnh trước, không hở nền
            a["t1"] = b["t0"]
    return beats


def _stock_terms(spec: Spec, beats: list[dict]) -> list[str]:
    """Từ khoá clip của kịch bản cho từng beat: "stock" của cảnh, thiếu thì xoay vòng stock_terms."""
    scenes = [s.model_extra or {} for s in spec.scenes]
    shared = spec.stock_terms or [spec.title]
    return [((scenes[b["scene"]].get("stock") or [None])[0] or shared[n % len(shared)]) for n, b in enumerate(beats)]


def _queries(spec: Spec, beats: list[dict], log, ai: bool = False) -> list[str]:
    """Mỗi beat một từ khoá tìm ảnh (Pexels) hoặc, khi vẽ bằng AI, một câu mô tả cảnh; cache theo nội dung câu."""
    own_note = (spec.model_extra or {}).get("image_note") if ai else None
    parts = [spec.title, [b["text"] for b in beats]] + ([own_note] if own_note else [])
    key = hashlib.sha1(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()[:16]
    f = CACHE / f"{'ai' if ai else 'q'}-{key}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    try:
        from .llm import _call_gemini, _json

        numbered = "\n".join(f"{n + 1}. {b['text']}" for n, b in enumerate(beats))
        # Tìm ảnh: tông chung lấy từ từ khoá clip (từ khoá của bản podcast là cho MoneyPrinterTurbo). Vẽ ảnh: chỉ tả
        # ánh sáng/màu — 06/10 đưa từ khoá clip vào đây thì Gemini vẽ "forest canopy looking up" cho cả 16 câu.
        if ai:
            mood = (spec.model_extra or {}).get("image_mood") or "warm natural light, cinematic colour"
        else:
            mood = ", ".join(spec.stock_terms[:3]) or "warm, cinematic"
        prompt = (AI_PROMPT if ai else QUERY_PROMPT).format(title=spec.title, mood=mood, numbered=numbered, n=len(beats),
                                                            note=own_note or AI_NOTE)
        for attempt in (1, 2):
            data = _json(_call_gemini(prompt, log=log))
            qs = [str(q).strip() for q in data.get("queries", [])]
            if len(qs) != len(beats) or not all(qs):
                raise ValueError(f"trả {len(qs)} từ khoá cho {len(beats)} câu")
            heads = {" ".join(q.lower().split()[:4]) for q in qs}
            if not ai or len(beats) < 4 or len(heads) >= 0.6 * len(qs):
                break
            log(f"mô tả cảnh lặp nhau ({len(heads)} kiểu cho {len(qs)} câu) → nhờ Gemini viết lại")
    except Exception as exc:
        log(f"Gemini chưa đặt được {'mô tả cảnh' if ai else 'từ khoá ảnh'} ({str(exc)[:90]}) → dùng từ khoá clip của kịch bản")
        qs = _stock_terms(spec, beats)
    CACHE.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(qs, ensure_ascii=False), encoding="utf-8")
    return qs


def _search(query: str, key: str) -> list[dict]:
    f = CACHE_DIR / "stock" / "photo-search" / f"{hashlib.sha1(query.lower().encode()).hexdigest()[:16]}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    params = {"query": query, "orientation": "portrait", "per_page": 15}
    if not query.isascii():
        params["locale"] = "vi-VN"
    for attempt in range(3):   # Pexels thỉnh thoảng trả 500 với một từ khoá: thử lại, rồi bỏ qua để dùng từ khoá dự phòng
        try:
            r = httpx.get("https://api.pexels.com/v1/search", headers={"Authorization": key}, params=params, timeout=30)
        except httpx.TransportError:
            r = None
        if r is not None and (r.status_code < 500 and r.status_code != 429):
            break
        time.sleep(2 * (attempt + 1))
    else:
        return []
    r.raise_for_status()
    photos = [{"id": p["id"], "url": p["src"]["original"]} for p in r.json().get("photos", [])]
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(photos), encoding="utf-8")
    return photos


def _pexels(query: str, used: set, key: str) -> Path | None:
    for p in _search(query, key):
        if p["id"] in used:
            continue
        used.add(p["id"])
        dst = PHOTOS / f"pexels-{p['id']}.jpg"
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            r = httpx.get(p["url"] + "?auto=compress&cs=tinysrgb&fit=crop&w=1080&h=1920", timeout=60, follow_redirects=True)
            r.raise_for_status()
            dst.write_bytes(r.content)
        return dst
    return None


def _gemini(prompt: str) -> Path | None:
    dst = CACHE / "ai" / f"{hashlib.sha1(prompt.encode()).hexdigest()[:16]}.png"
    if dst.exists():
        return dst
    body = {"contents": [{"parts": [{"text": f"{prompt}. {AI_STYLE}"}]}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "9:16"}}}
    r = httpx.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent",
                   headers={"x-goog-api-key": gemini_api_key() or ""}, json=body, timeout=180)
    if r.status_code != 200:
        return None
    parts = (r.json().get("candidates") or [{}])[0].get("content", {}).get("parts", [])
    img = next((p["inlineData"]["data"] for p in parts if "inlineData" in p), None)
    if not img:
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(base64.b64decode(img))
    return dst


def comfyui_url() -> str:
    return (os.environ.get("COMFYUI_URL") or _read_dotenv().get("COMFYUI_URL") or "http://127.0.0.1:8188").rstrip("/")


def _comfyui(prompt: str, log, variant: int = 0) -> Path | None:
    """Vẽ một ảnh dọc 768×1344 bằng SDXL-Lightning 4 bước (euler, sgm_uniform, cfg 1 — theo hướng dẫn của ByteDance).

    variant > 0: cùng mô tả nhưng seed khác (cảnh dài cần nhiều ảnh cho đỡ lặp)."""
    tag = prompt if not variant else f"{prompt}#{variant}"
    seed = int(hashlib.sha1(tag.encode()).hexdigest()[:8], 16)
    dst = CACHE / "ai" / f"comfy-{hashlib.sha1(f'{COMFY_CKPT}|{tag}'.encode()).hexdigest()[:16]}.jpg"
    with _comfy_lock:
        if dst.exists():
            return dst
        graph = {
            "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": COMFY_CKPT}},
            "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 768, "height": 1344, "batch_size": 1}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": f"{prompt}, {COMFY_STYLE}", "clip": ["4", 1]}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["4", 1]}},
            "3": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": 4, "cfg": 1.0, "sampler_name": "euler",
                                                       "scheduler": "sgm_uniform", "denoise": 1.0, "model": ["4", 0],
                                                       "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
            "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "video-factory", "images": ["8", 0]}},
        }
        base = comfyui_url()
        try:
            r = httpx.post(f"{base}/prompt", json={"prompt": graph}, timeout=30)
            r.raise_for_status()
            pid = r.json()["prompt_id"]
            for _ in range(600):                                   # tối đa ~5 phút (lần đầu phải nạp model)
                h = httpx.get(f"{base}/history/{pid}", timeout=30).json().get(pid)
                if h and h.get("outputs"):
                    img = h["outputs"]["9"]["images"][0]
                    break
                if h and h.get("status", {}).get("status_str") == "error":
                    log(f"ComfyUI báo lỗi khi vẽ '{prompt[:60]}'")
                    return None
                time.sleep(0.5)
            else:
                log("ComfyUI vẽ quá 5 phút — bỏ qua")
                return None
            png = httpx.get(f"{base}/view", params={k: img[k] for k in ("filename", "subfolder", "type")}, timeout=60)
            png.raise_for_status()
        except httpx.HTTPError as exc:
            log(f"không gọi được ComfyUI ở {base} ({type(exc).__name__}) — đã bật python3 chay-comfyui.py chưa?")
            return None
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(".png")
        tmp.write_bytes(png.content)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp), "-q:v", "2", str(dst)], check=True)   # PNG ~1,5 MB → JPEG
        tmp.unlink(missing_ok=True)
        return dst


def attach(spec: Spec, data: dict, dest: Path, prefix: str, log, *, credits_out: Path | None = None) -> int:
    """Gắn data["beats"] = [{t0, t1, src, q, scene, text}] và chép ảnh vào `dest` (src = prefix + tên file).

    Trả về số ảnh. Các engine khác nhau dùng chung từ khoá (cache theo nội dung câu) nên ra cùng bộ ảnh."""
    if (spec.model_extra or {}).get("images") is False:
        return 0
    beats = plan(data)
    source, provider = _source(spec), stock_provider(spec)
    key = stock_api_key(provider)
    stock_photo = pixabay.photo if provider == "pixabay" else _pexels
    ai = source in ("gemini", "comfyui")
    if not beats or not (key or ai):
        return 0
    with _lock:   # HyperFrames và Remotion chạy song song: chỉ một bên nhờ Gemini đặt từ khoá, bên kia dùng cache
        queries = _queries(spec, beats, log, ai=ai)
    terms = _stock_terms(spec, beats)
    used, out, drawn, ai_failed = set(), [], 0, False
    dest.mkdir(parents=True, exist_ok=True)
    for n, (b, q) in enumerate(zip(beats, queries)):
        img = None
        if ai and not ai_failed:
            img = _gemini(q) if source == "gemini" else _comfyui(q, log)
            ai_failed = img is None          # một lần lỗi (chưa bật ComfyUI, hết hạn mức) thì các câu sau dùng Pexels luôn
            drawn += img is not None
        if not img and key:
            search = terms[n] if ai else q   # mô tả cảnh dài của AI không hợp để tìm trên Pexels
            try:
                img = stock_photo(search, used, key) or stock_photo(spec.stock_terms[0] if spec.stock_terms else spec.title, used, key)
            except (httpx.HTTPError, RuntimeError) as exc:
                log(f"{provider.title()} lỗi với '{search}': {exc}")
        if not img:
            continue
        name = f"b{len(out):02d}{img.suffix}"
        shutil.copy2(img, dest / name)
        out.append({"t0": round(b["t0"], 3), "t1": round(b["t1"], 3), "src": f"{prefix}{name}", "q": q,
                    "scene": b["scene"], "text": b["text"], "provider": provider if not ai or ai_failed else source,
                    "page": json.loads(img.with_suffix('.json').read_text()).get('page', '')
                    if img.name.startswith('pixabay-') and img.with_suffix('.json').exists() else ''})
    data["beats"] = out
    pages = list(dict.fromkeys(b['page'] for b in out if b.get('page')))
    if pages:
        (credits_out or dest.parent / "credits.txt").write_text("Ảnh: Pixabay\n" + "\n".join(pages) + "\n", encoding="utf-8")
    where = {"comfyui": "ComfyUI", "gemini": "Gemini"}.get(source, "Pexels")
    log(f"ảnh theo câu: {len(out)} ảnh" + (f" ({drawn} ảnh vẽ bằng {where}, còn lại {provider.title()})" if ai else f" ({provider.title()})"))
    return len(out)


def _zoom_clip(img: Path, seconds: float, out: Path) -> None:
    """Một ảnh → clip dọc 1080×1920, 30 khung/giây, zoom chậm 1,00 → 1,08 trong đúng `seconds` giây.

    Phóng ảnh lên 1620×2880 trước khi zoompan để chuyển động mượt (zoompan làm tròn toạ độ theo điểm ảnh); 2160×3840
    mượt hơn chút nhưng chậm gần gấp đôi (~7 giây/clip)."""
    frames = max(1, round(seconds * 30))
    vf = ("scale=1620:2880:force_original_aspect_ratio=increase,crop=1620:2880,"
          f"zoompan=z='1+0.08*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1080x1920:fps=30")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(img), "-vf", vf, "-frames:v", str(frames),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", str(out)], check=True)


CONJ = {"và", "nhưng", "nên", "còn"}


def phrases(words: list[dict], duration: float, min_len: float = 1.0, long: float = 4.0) -> list[dict]:
    """Băm lời đọc theo vế câu để hình đổi nhanh: tách ở dấu câu và dấu phẩy; vế dài hơn `long` giây tách thêm trước liên
    từ (và, nhưng, nên, còn) nếu hai nửa đều ≥ 1,5 giây; vế ngắn hơn `min_len` giây gộp vào vế SAU ("Năm 2019," đi với
    "các nhà khoa học…", "Nhờ vậy," đi với "phần não…"). Trả [{t0, t1, text}], t0 sớm hơn lời BEAT_LEAD giây."""
    span = lambda seg: seg[-1]["end"] - seg[0]["start"]
    todo, segs = list(_sentences(words, PHRASE_END)), []
    while todo:
        seg = todo.pop(0)
        cut = next((i for i in range(1, len(seg)) if span(seg) > long and seg[i]["display"].lower().strip(",.") in CONJ
                    and span(seg[:i]) >= 1.5 and span(seg[i:]) >= 1.5), None)
        if cut:
            todo[:0] = [seg[:cut], seg[cut:]]
        else:
            segs.append(seg)
    merged, carry = [], []
    for n, seg in enumerate(segs):
        seg = carry + seg
        carry = seg if span(seg) < min_len and n + 1 < len(segs) else []
        if not carry:
            merged.append(seg)
    beats = [{"t0": 0.0 if n == 0 else max(0.0, seg[0]["start"] - BEAT_LEAD), "text": " ".join(w["display"] for w in seg)}
             for n, seg in enumerate(merged)]
    for a, b in zip(beats, beats[1:]):
        a["t1"] = b["t0"]
    if beats:
        beats[-1]["t1"] = duration
    return beats


CLOSE_UP = "Extreme close-up macro photo of leaves and plants filling the frame, softly blurred background. "
SHOTS = ["", "close-up detail", "wide shot"]   # vế dài được thêm cảnh: cùng chủ thể, đổi cỡ cảnh cho khỏi lặp


CHECK_PROMPT = """The numbered images above are backgrounds for a video. None of them may show any of these: {forbid}.
Look carefully, including small details far in the background (a faint footpath through grass or a forest counts).
Return ONLY JSON: {{"bad": [numbers of the images that show any of them]}}."""


def _flag_forbidden(images: list[Path], forbid: str, log) -> set[int] | None:
    """Gemini soát một lượt cả loạt ảnh (thu nhỏ 320 px) và chỉ ra ảnh có thứ bị cấm — SDXL-Lightning chạy cfg 1 nên không
    có prompt phủ định, lại hay tự vẽ lối mòn khi tả nền rừng/đồng cỏ (06/10). Trả chỉ số ảnh xấu, None nếu không soát được."""
    from .llm import _call_gemini, _json

    thumbs = [subprocess.run(["ffmpeg", "-v", "error", "-i", str(f), "-vf", "scale=320:-2", "-q:v", "5", "-f", "image2pipe",
                              "-vcodec", "mjpeg", "-"], check=True, capture_output=True).stdout for f in images]
    try:
        bad = _json(_call_gemini(CHECK_PROMPT.format(forbid=forbid), log=log, images=thumbs)).get("bad", [])
        return {int(n) - 1 for n in bad if 0 < int(n) <= len(images)}
    except Exception as exc:
        log(f"chưa soát được ảnh bằng Gemini ({str(exc)[:80]}) — nên tự xem lại")
        return None


COMMONS_API = "https://commons.wikimedia.org/w/api.php"
COMMONS_UA = {"User-Agent": "video-factory/1.0 (personal video tool; Windows)"}   # Wikimedia đòi User-Agent mô tả rõ
COMMONS_PROMPT = """You pick REAL photos from Wikimedia Commons for a Vietnamese factual video titled "{title}".
For each numbered phrase return "shots": 1-3 photos in the order the phrase mentions them — one per distinct person,
event or object it names (a list of three names gives three shots). Each shot has:
- "query": a SHORT English Commons search query (3-6 words; Commons matches every word) for a real photo of exactly that
  subject, e.g. "Trump Kim Singapore summit".
- "who": the surname of the person who must be IN the photo, as Commons titles write it (e.g. "Trump"), or null if the shot
  is about a place or object only.
- "what": 0-2 keywords for the event, place or object that must appear in the photo's title or description (e.g.
  ["Singapore"]); never generic words like "president", "photo", "speech".
- "year": the year the photo should be from (e.g. 2018), or null if any recent year is fine.
- "fallback": a short query for a photo of the named thing itself in case no photo of that exact moment exists, and
  "fallback_who" / "fallback_what" for it.
If a phrase names nothing specific, give one shot of the most relevant concrete subject of the surrounding phrases.
Phrases:
{numbered}
Return ONLY JSON: {{"items": [{{"shots": [{{"query": "...", "who": "...", "what": ["..."], "year": 2018, "fallback": "...",
"fallback_who": null, "fallback_what": ["..."]}}]}}]}} with exactly {n} items, in order."""
FREE = ("public domain", "pd", "cc0", "cc by")   # giấy phép cho dùng lại (CC BY/BY-SA phải ghi tác giả)
_commons_gate = threading.Lock()
_commons_last = [0.0]


def _commons_get(url: str, **kw) -> httpx.Response:
    """Gọi Wikimedia cách nhau ≥ 1 giây, gặp 429 thì chờ (theo Retry-After) rồi thử lại — 07/10 gọi dồn bị chặn 429."""
    for attempt in range(5):
        with _commons_gate:
            wait = _commons_last[0] + 1.0 - time.time()
            if wait > 0:
                time.sleep(wait)
            r = httpx.get(url, headers=COMMONS_UA, timeout=60, follow_redirects=True, **kw)
            _commons_last[0] = time.time()
        if r.status_code != 429:
            r.raise_for_status()
            return r
        delay = float(r.headers.get("retry-after") or 0) or 5.0 * (attempt + 1)
        time.sleep(min(delay, 60))
    r.raise_for_status()
    return r


def _commons_plan(spec: Spec, beats: list[dict], log) -> list[dict]:
    """Mỗi vế 1–3 cảnh, mỗi cảnh một truy vấn Commons + từ khoá bắt buộc (cache theo nội dung vế)."""
    key = hashlib.sha1(json.dumps([spec.title, [b["text"] for b in beats]], ensure_ascii=False).encode()).hexdigest()[:16]
    f = CACHE / f"commons4-{key}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    from .llm import _call_gemini, _json

    numbered = "\n".join(f"{n + 1}. {b['text']}" for n, b in enumerate(beats))
    items = _json(_call_gemini(COMMONS_PROMPT.format(title=spec.title, numbered=numbered, n=len(beats)), log=log)).get("items", [])
    ok = len(items) == len(beats) and all(isinstance(x, dict) and x.get("shots") and all(s.get("query") for s in x["shots"])
                                          for x in items)
    if not ok:
        raise ValueError(f"Gemini trả {len(items)} mục cho {len(beats)} vế")
    CACHE.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return items


def _strip_html(text) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(text or ""))).strip()


def _commons_search(query: str) -> list[dict]:
    """Ảnh JPEG trên Commons theo truy vấn, đã lọc giấy phép tự do, xếp theo độ liên quan (cache)."""
    f = CACHE_DIR / "commons" / f"search3-{hashlib.sha1(query.lower().encode()).hexdigest()[:16]}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    params = {"action": "query", "format": "json", "generator": "search", "gsrsearch": query, "gsrnamespace": 6,
              "gsrlimit": 30, "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1280}   # kích cỡ chuẩn của Wikimedia (cỡ lẻ bị chặn 429)
    r = _commons_get(COMMONS_API, params=params)
    out = []
    for page in sorted((r.json().get("query") or {}).get("pages", {}).values(), key=lambda x: x.get("index", 0)):
        info = (page.get("imageinfo") or [{}])[0]
        meta = {k: (v or {}).get("value", "") for k, v in (info.get("extmetadata") or {}).items()}
        lic = _strip_html(meta.get("LicenseShortName"))
        if info.get("mime") != "image/jpeg" or info.get("width", 0) < 900 or not info.get("thumburl"):
            continue
        if not lic.lower().startswith(FREE) or "fair use" in lic.lower():
            continue
        out.append({"title": page["title"], "thumb": info["thumburl"], "page": info.get("descriptionurl", ""),
                    "license": lic, "artist": _strip_html(meta.get("Artist"))[:120],
                    "date": _strip_html(meta.get("DateTimeOriginal"))[:40],
                    "desc": _strip_html(meta.get("ImageDescription"))[:220],
                    "text": " ".join([page["title"], _strip_html(meta.get("ObjectName")),
                                      _strip_html(meta.get("ImageDescription")),
                                      str(meta.get("Categories", "")).replace("|", " ")])})
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def _commons_file(title: str) -> dict | None:
    """Thông tin một file Commons theo tên chính xác ("File:…"), cùng dạng kết quả tìm kiếm (cache). Không lọc giấy phép ở
    đây vì người ghim đã chọn — nhưng vẫn bỏ nếu không phải giấy phép tự do."""
    f = CACHE_DIR / "commons" / f"file-{hashlib.sha1(title.encode()).hexdigest()[:16]}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8")) or None
    params = {"action": "query", "format": "json", "titles": title, "prop": "imageinfo",
              "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1280}
    page = next(iter((_commons_get(COMMONS_API, params=params).json().get("query") or {}).get("pages", {}).values()), {})
    info = (page.get("imageinfo") or [{}])[0]
    meta = {k: (v or {}).get("value", "") for k, v in (info.get("extmetadata") or {}).items()}
    lic = _strip_html(meta.get("LicenseShortName"))
    out = {}
    if info.get("thumburl") and lic.lower().startswith(FREE) and "fair use" not in lic.lower():
        out = {"title": page["title"], "thumb": info["thumburl"], "page": info.get("descriptionurl", ""), "license": lic,
               "artist": _strip_html(meta.get("Artist"))[:120], "date": _strip_html(meta.get("DateTimeOriginal"))[:40],
               "desc": _strip_html(meta.get("ImageDescription"))[:220], "text": page["title"]}
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out or None


def _plain_text(text: str) -> str:
    import unicodedata as u

    text = u.normalize("NFD", str(text)).replace("đ", "d").replace("Đ", "D")
    return " ".join(re.sub(r"[^\w]+", " ", "".join(ch for ch in text if u.category(ch) != "Mn").lower()).split())


CHOOSE_PROMPT = """You check photos for a Vietnamese factual video titled "{title}". For each numbered scene you get the
phrase being spoken and candidate Wikimedia Commons photos (title, date taken, description). Accept a candidate only if
it shows EXACTLY what the phrase is about: the right person, event, object or place, at the right time (a 2009 Senate
photo does not show a 2021 vote; a memorial seen from the White House is not the White House; another politician is not
Trump). For a phrase that is only a time or transition ("In 2020,"), accept a photo of the main subject of the video from
that time. List acceptable letters best first; give [] when none is exactly right.
{scenes}
Return ONLY JSON keyed by scene number, one entry for each of the {n} scenes above:
{{"picks": {{"<scene number>": ["a", "c"], "<scene number>": []}}}}"""


def _year_of(c: dict) -> int | None:
    m = re.search(r"\b(1[89]\d\d|20\d\d)\b", f"{c.get('date') or ''} {c['title']}")
    return int(m.group(1)) if m else None


def _commons_candidates(shot: dict, log) -> list[dict]:
    """Ứng viên cho một cảnh, lọc bằng quy tắc cố định (07/10: lọc lỏng thì câu "ông ký luật thuế" ra ảnh Mike Pence,
    "Thượng viện tuyên trắng án" ra ảnh Thượng viện năm 2009):
    - người ("who") phải có trong TÊN ảnh, không chỉ trong mô tả; sự kiện/vật ("what") có trong tên hoặc mô tả;
    - năm chụp lệch năm sự kiện tối đa 1 năm (khi biết cả hai); không biết năm sự kiện thì bỏ ảnh trước 1950;
    - xếp theo số chữ của truy vấn có trong tên ảnh, rồi thứ hạng tìm kiếm.
    Tối đa 6 ảnh của truy vấn chính + 3 ảnh của truy vấn dự phòng."""
    out = []
    for query, who, what, limit in ((shot.get("query"), shot.get("who"), shot.get("what") or [], 6),
                                    (shot.get("fallback"), shot.get("fallback_who"), shot.get("fallback_what") or [], 3)):
        if not query:
            continue
        who_n = _plain_text(who) if who else ""
        what_n = [_plain_text(w) for w in what if str(w).strip()]
        words = set(_plain_text(query).split())
        year = shot.get("year") if isinstance(shot.get("year"), int) else None
        try:
            found = _commons_search(query)
        except httpx.HTTPError as exc:
            log(f"Commons lỗi với '{query}': {exc}")
            continue
        ok = []
        for rank, c in enumerate(found):
            title, text = _plain_text(c["title"]), _plain_text(c["text"])
            if who_n and who_n not in title:
                continue
            if not all(w in text for w in what_n):
                continue
            y = _year_of(c)
            if y and ((year and abs(y - year) > 1) or (not year and y < 1950)):
                continue
            ok.append((-len(words & set(title.split())), rank, c))
        ok.sort(key=lambda x: (x[0], x[1]))
        out += [c for _, _, c in ok if c["title"] not in {x["title"] for x in out}][:limit]
    return out


def _commons_choose(spec: Spec, rows: list[tuple[str, list[dict]]], log, batch: int = 10) -> list[list[int]] | None:
    """Gemini duyệt theo lô `batch` cảnh (đánh số): trả chỉ số ứng viên chấp nhận được (tốt nhất trước) cho từng cảnh;
    cảnh Gemini bỏ sót coi như không có ảnh đúng. None nếu không duyệt được lô nào (Gemini lỗi hẳn)."""
    from .llm import _call_gemini, _json

    letters = "abcdefghij"
    picks: list[list[int]] = [[] for _ in rows]
    done = 0
    for lo in range(0, len(rows), batch):
        chunk = list(enumerate(rows))[lo:lo + batch]
        blocks = []
        for i, (text, cands) in chunk:
            lines = [f"Scene {i + 1}: \"{text}\""] + [f"  {letters[k]}) {c['title'][5:]} | date: {c.get('date') or '?'}"
                                                       f" | {c.get('desc') or ''}" for k, c in enumerate(cands)]
            blocks.append("\n".join(lines if cands else lines + ["  (no candidates)"]))
        prompt = CHOOSE_PROMPT.format(title=spec.title, scenes="\n\n".join(blocks), n=len(chunk))
        for attempt in (1, 2):
            try:
                got = _json(_call_gemini(prompt, log=log)).get("picks", {})
                break
            except Exception as exc:
                got = None
                log(f"Gemini chưa duyệt được ảnh cảnh {lo + 1}–{lo + len(chunk)} ({str(exc)[:60]})")
        if got is None:
            continue
        done += 1
        if isinstance(got, list):   # trả danh sách theo thứ tự thay vì đánh số
            got = {str(chunk[k][0] + 1): v for k, v in enumerate(got[:len(chunk)])}
        if isinstance(got, dict) and not any(str(i + 1) in got for i, _ in chunk) and lo:
            got = {str(chunk[int(k) - 1][0] + 1): v for k, v in got.items()   # lô sau bị đánh số lại từ 1
                   if str(k).isdigit() and 0 < int(k) <= len(chunk)}
        lot = {}
        for i, (_, cands) in chunk:
            pk = got.get(str(i + 1)) if isinstance(got, dict) else None
            lot[i] = [letters.index(x) for x in (pk or []) if isinstance(x, str) and x in letters[:len(cands)]]
        with_cands = [i for i, (_, cands) in chunk if cands]
        if len(with_cands) >= 3 and not any(lot[i] for i in with_cands):   # loại sạch: Gemini (bản nhẹ, quá tải) trả bậy
            log(f"Gemini loại hết ảnh cảnh {lo + 1}–{lo + len(chunk)} — bỏ qua lượt duyệt này, dùng thứ tự đã lọc")
            for i, (_, cands) in chunk:
                picks[i] = list(range(len(cands)))
            continue
        for i, v in lot.items():
            picks[i] = v
    return picks if done else None


def _commons_still(c: dict) -> Path:
    """Tải ảnh và dựng khung dọc 1080×1920: ảnh gốc nguyên vẹn ở giữa, nền là chính ảnh đó phóng to, làm mờ, tối đi
    (ảnh báo chí thường nằm ngang — cắt cho vừa khung dọc sẽ mất người ở hai bên)."""
    folder = CACHE_DIR / "commons"
    name = hashlib.sha1(c["thumb"].encode()).hexdigest()[:16]
    src, still = folder / f"{name}.jpg", folder / f"{name}-dung.jpg"
    if not still.exists():
        if not src.exists():
            folder.mkdir(parents=True, exist_ok=True)
            src.write_bytes(_commons_get(c["thumb"]).content)
        vf = ("[0]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=28:4,eq=brightness=-0.18[bg];"
              "[0]scale=1080:1920:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-filter_complex", vf, "-q:v", "2", str(still)],
                       check=True)
    return still


def _commons_images(spec: Spec, items: list[dict] | None, beats: list[dict], shots: list[tuple[int, int, float]],
                    log, pinned: dict[int, str] | None = None) -> tuple[list[Path], list[dict]]:
    """Ảnh thật từ Commons cho từng cảnh (vế, thứ tự cảnh trong vế, số giây): cảnh j của vế dùng chủ thể thứ j Gemini
    liệt kê (vd. ba thẩm phán → ba ảnh). Ứng viên phải chứa đủ từ khoá bắt buộc, rồi Gemini duyệt theo tên/ngày/mô tả
    — 07/10 chỉ lọc từ khoá thì 10/46 cảnh sai (tờ tiền năm 1862 cho câu về thuế, Thượng viện khoá 2009 cho vụ 2021…).
    Không có ảnh đúng thì giữ ảnh cảnh trước. Trả (ảnh theo thứ tự cảnh, nguồn ảnh)."""
    pinned = pinned or {}
    rows = []
    for i, (n, j, _) in enumerate(shots):
        if i in pinned:   # cảnh đã ghim: chỉ một ứng viên, không cần Gemini duyệt
            c = _commons_file(pinned[i])
            if c is None:
                log(f"không lấy được file ghim {pinned[i]} (sai tên hoặc không phải giấy phép tự do)")
            rows.append((beats[n]["text"], [c] if c else []))
            continue
        subjects = items[n]["shots"]
        rows.append((beats[n]["text"], _commons_candidates(subjects[min(j, len(subjects) - 1)], log)))
    todo = [i for i in range(len(rows)) if i not in pinned]
    picks = [[0] if rows[i][1] else [] for i in range(len(rows))]
    if todo:
        got = _commons_choose(spec, [rows[i] for i in todo], log)
        for k, i in enumerate(todo):
            picks[i] = got[k] if got else list(range(len(rows[i][1])))
    used, images, credits, last, kept, failed = set(), [], [], None, 0, 0
    for (text, cands), ok in zip(rows, picks):
        c = next((cands[k] for k in ok if cands[k]["title"] not in used), None)
        if c is None:
            kept += 1
            if last is not None:
                images.append(last)
                continue
            c = next((x for x in cands if x["title"] not in used), None)   # cảnh đầu tiên mà chưa có ảnh trước
            if c is None:
                return [], []
        used.add(c["title"])
        try:
            last = _commons_still(c)
        except httpx.HTTPError as exc:   # Wikimedia giới hạn tần suất (429) giữa chừng: giữ ảnh trước, đếm lỗi
            failed += 1
            log(f"chưa tải được {c['title'][5:60]} ({str(exc)[:40]})")
            if last is None or failed > len(rows) // 4:
                log(f"tải lỗi {failed} ảnh — dừng, chạy lại sau ít phút (ảnh đã tải được giữ trong cache)")
                return [], []
            images.append(last)
            continue
        images.append(last)
        credits.append(c)
    if kept or failed:
        log(f"{kept} cảnh không có ảnh đúng hẳn, {failed} ảnh tải lỗi → giữ ảnh cảnh trước")
    return images, credits


def sentence_clips(spec: Spec, words: list[dict], duration: float, dest: Path, log, target: float = 2.2,
                   credits_out: Path | None = None) -> list[Path]:
    """Hình cho từng vế câu, dựng sẵn thành clip zoom dài đúng thời lượng vế đó (đổi sớm hơn lời BEAT_LEAD giây).

    Dùng cho MoneyPrinterTurbo: nó chỉ biến ảnh thành đoạn dài cố định rồi ghép, nên hình lệch lời; đưa nó clip dựng sẵn
    (chế độ local + sequential) thì hình đổi đúng lúc. Băm theo vế (dấu phẩy, hai chấm…), mỗi vế một hình riêng; vế dài
    hơn `target` giây thêm cảnh — nhịp đổi hình ~2 giây như video TikTok. Nguồn hình theo "image_source":
    - comfyui / gemini: vẽ AI (mô tả cảnh do Gemini viết); "image_forbid" thì Gemini soát ảnh, ảnh vi phạm được vẽ lại.
    - commons: ảnh THẬT trên Wikimedia Commons cho video nói về người/sự kiện có thật (ảnh AI chỉ "giống", lại dễ bị
      hiểu nhầm là ảnh thật): Gemini đặt truy vấn + từ khoá bắt buộc phải có trong tên/mô tả ảnh, chỉ lấy ảnh giấy phép
      tự do; nguồn ảnh ghi vào `credits_out` để dán vào mô tả khi đăng.
    `words` là mốc từng từ của giọng đọc sẽ dùng (đã gắn dấu câu). Trả [] nếu nguồn hình không dùng được."""
    source = _source(spec)
    if source not in ("comfyui", "gemini", "commons", "pixabay") or (spec.model_extra or {}).get("images") is False:
        return []
    beats = [dict(b, scene=0) for b in phrases(words, duration)]
    if not beats:
        return []
    spans = []   # (chỉ số vế, số giây) cho từng cảnh theo thứ tự
    for n, b in enumerate(beats):
        span = (b["t1"] if n + 1 < len(beats) else duration + 1.0) - b["t0"]   # thêm 1 giây đuôi cho vế cuối
        count = max(1, round(span / target))
        spans += [(n, span / count)] * count

    if source == "pixabay":
        with _lock:
            queries = _queries(spec, beats, log)
        used, images, pages = set(), [], []
        key = stock_api_key("pixabay")
        for n, _ in spans:
            image = pixabay.photo(queries[n], used, key) or pixabay.photo(spec.stock_terms[0] if spec.stock_terms else spec.title, set(), key)
            if image is None:
                return []
            images.append(image)
            if image.with_suffix('.json').exists():
                pages.append(json.loads(image.with_suffix('.json').read_text()).get('page', ''))
        if credits_out:
            credits_out.write_text("Ảnh: Pixabay\n" + "\n".join(dict.fromkeys(pages)) + "\n", encoding="utf-8")
    elif source == "commons":
        try:
            pins = (spec.model_extra or {}).get("image_pins") or []
            pin_of = {}
            for n, b in enumerate(beats):   # ghim khớp vế nếu đoạn "match" nằm trong vế (lấy đoạn khớp dài nhất)
                hits = [x for x in pins if x.get("files") and _plain_text(x.get("match", "")) in _plain_text(b["text"])]
                if hits:
                    pin_of[n] = max(hits, key=lambda x: len(x["match"]))["files"]
            items = _commons_plan(spec, beats, log) if len(pin_of) < len(beats) else None
            shots_c, spans, pinned = [], [], {}
            for n, b in enumerate(beats):
                span = (b["t1"] if n + 1 < len(beats) else duration + 1.0) - b["t0"]
                if n in pin_of:
                    count = len(pin_of[n])
                    pinned.update({len(shots_c) + j: pin_of[n][j] for j in range(count)})
                else:
                    count = max(len(items[n]["shots"]), round(span / target), 1)   # ba cái tên → ba cảnh, theo thứ tự đọc
                shots_c += [(n, j, span / count) for j in range(count)]
                spans += [(n, span / count)] * count
            if pin_of:
                log(f"ảnh ghim sẵn: {len(pin_of)}/{len(beats)} vế")
            images, credits = _commons_images(spec, items, beats, shots_c, log, pinned)
        except Exception as exc:
            log(f"chưa lấy được ảnh Commons ({str(exc)[:100]}) → MoneyPrinterTurbo dùng clip Pexels như thường")
            return []
        if not images:
            return []
        if credits_out:
            lines = [f"- {c['title'].removeprefix('File:')} — {c['artist'] or 'không rõ tác giả'}, {c['license']} "
                     f"({c['page']})" for c in credits]
            credits_out.write_text("Ảnh: Wikimedia Commons\n" + "\n".join(lines) + "\n", encoding="utf-8")
        log(f"ảnh thật Wikimedia Commons: {len(credits)} ảnh cho {len(beats)} vế")
    else:
        with _lock:
            queries = _queries(spec, beats, log, ai=True)
        shots = []   # (mô tả, biến thể) cho từng cảnh
        seen: dict[int, int] = {}
        for n, _ in spans:
            k = seen[n] = seen.get(n, -1) + 1
            shots.append((f"{queries[n]}, {SHOTS[k % len(SHOTS)]}" if k else queries[n], k))

        def draw(text: str, variant: int) -> Path | None:
            return _gemini(text) if source == "gemini" else _comfyui(text, log, variant=variant)

        images = [draw(text, k) for text, k in shots]
        if None in images:
            log("vẽ ảnh lỗi → MoneyPrinterTurbo dùng clip Pexels như thường")
            return []
        forbid = (spec.model_extra or {}).get("image_forbid")
        if forbid and source == "comfyui":
            for round_ in (1, 2, 3):
                bad = _flag_forbidden(images, forbid, log)
                if not bad:
                    if bad is not None:
                        log(f"Gemini soát {len(images)} ảnh lượt {round_}: không còn ảnh vi phạm")
                    break
                nums = ", ".join(str(i + 1) for i in sorted(bad))
                log(f"Gemini soát ảnh lượt {round_}: {len(bad)} ảnh có thứ bị cấm ({nums}) → vẽ lại"
                    + (" sang cận cảnh" if round_ >= 2 else ""))
                for i in bad:
                    text, k = shots[i]
                    if round_ >= 2:   # đổi seed không đủ (vd. "hàng cây" luôn kèm con đường): cận cảnh, đặt ĐẦU mô tả cho
                        text = CLOSE_UP + text   # CLIP coi trọng phần đầu — 07/10 gắn ở cuối thì model vẫn vẽ con đường
                    images[i] = draw(text, k + 100 * round_) or images[i]
                if round_ == 3:
                    log(f"lượt cuối: {len(bad)} cảnh ({nums}) đã chuyển sang cận cảnh, không soát lại")
    dest.mkdir(parents=True, exist_ok=True)
    clips: list[Path] = []
    for img, (_, seconds) in zip(images, spans):
        out = dest / f"{len(clips):03d}.mp4"
        _zoom_clip(img, seconds, out)
        clips.append(out)
    log(f"hình theo vế câu: {len(beats)} vế → {len(clips)} clip, trung bình {duration / max(1, len(clips)):.1f} giây/cảnh")
    return clips
