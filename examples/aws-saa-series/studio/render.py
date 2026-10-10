# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright>=1.50", "edge-tts==7.2.7"]
# ///
"""Render một tập AWS SAA thành video motion graphics (HTML -> khung hình -> MP4).

    uv run render.py 5                  # xuất ../output-v2/Tap-05 - ....mp4
    uv run render.py 5 --preview 3,12   # chỉ chụp vài khung hình PNG để xem nhanh

Kịch bản cảnh nằm trong scenes/epNN.json. Mỗi cảnh có lời đọc riêng ("say"); giọng đọc
Edge TTS trả về mốc thời gian từng từ, nên sơ đồ và phụ đề khớp đúng lúc từ được đọc.
Dùng Chrome cài sẵn trên máy (channel="chrome"), không tải trình duyệt riêng.
"""

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

HERE = Path(__file__).resolve().parent
SERIES_DIR = HERE.parent
OUT_DIR = SERIES_DIR / "output-v2"
CACHE_DIR = HERE / ".cache" / "tts"
PREVIEW_DIR = HERE / ".preview"
TEMPLATE = HERE / "template.html"

VOICE = "vi-VN-HoaiMyNeural"
RATE = "+0%"
FPS = 30
W, H = 1080, 1920
FIRST_LEAD = 0.6   # giây im lặng trước câu đầu tiên để khán giả kịp thấy tiêu đề
LEAD = 0.15        # khoảng lặng đầu mỗi cảnh
GAP = 0.4          # khoảng lặng cuối mỗi cảnh
TAIL = 1.2         # giữ khung cuối
WORKERS = 4
PUNCT = ",.:;!?…"


def norm(text: str) -> str:
    text = unicodedata.normalize("NFC", text).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def synthesize(text: str) -> tuple[Path, list[dict], float]:
    """Edge TTS có cache; trả về (mp3, danh sách từ có mốc thời gian, thời lượng)."""
    import edge_tts

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{VOICE}|{RATE}|{text}".encode()).hexdigest()[:16]
    mp3, meta = CACHE_DIR / f"{key}.mp3", CACHE_DIR / f"{key}.json"
    if mp3.exists() and meta.exists():
        words = json.loads(meta.read_text(encoding="utf-8"))
        return mp3, words, probe_duration(mp3)

    last_error = None
    for attempt in range(3):
        try:
            words = []
            comm = edge_tts.Communicate(text, VOICE, rate=RATE, boundary="WordBoundary", receive_timeout=90)
            with open(mp3, "wb") as f:
                for chunk in comm.stream_sync():
                    if chunk["type"] == "audio":
                        f.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        start = chunk["offset"] / 1e7
                        words.append({"text": chunk["text"], "start": start, "end": start + chunk["duration"] / 1e7})
            if words:
                meta.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
                return mp3, words, probe_duration(mp3)
            last_error = "không nhận được mốc thời gian từ"
        except Exception as exc:  # mạng chập chờn: thử lại
            last_error = exc
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Edge TTS lỗi với câu: {text[:60]}...: {last_error}")


def attach_punctuation(text: str, words: list[dict]) -> None:
    """Gắn dấu câu từ lời đọc gốc vào từng từ để phụ đề hiển thị tự nhiên và biết chỗ ngắt."""
    pos = 0
    low = text.lower()
    for w in words:
        i = low.find(w["text"].lower(), pos)
        if i < 0:
            w["display"], w["brk"] = w["text"], False
            continue
        j = i + len(w["text"])
        trail = re.match(rf"[{re.escape(PUNCT)}]+", text[j:])
        w["display"] = text[i:j] + (trail.group(0) if trail else "")
        w["brk"] = bool(trail)
        pos = j


class CueFinder:
    """Tìm thời điểm một cụm từ được đọc trong cảnh, tìm tuần tự để cụm lặp lại không bị nhầm."""

    def __init__(self, words: list[dict], scene_label: str):
        self.words, self.label = words, scene_label
        self.joined, self.owner = "", []
        for idx, w in enumerate(words):
            token = norm(w["text"])
            if not token:
                continue
            if self.joined:
                self.joined += " "
                self.owner.append(idx)
            self.joined += token
            self.owner.extend([idx] * len(token))
        self.cursor = 0
        self.last_t = words[0]["start"] if words else 0.0

    def time_of(self, cue: str) -> float:
        needle = norm(cue)
        i = self.joined.find(needle, self.cursor)
        if i < 0:
            i = self.joined.find(needle)
        if i < 0:
            print(f"  ! không thấy cue '{cue}' trong cảnh {self.label}, dùng thời điểm ước lượng", file=sys.stderr)
            self.last_t += 0.8
            return self.last_t
        self.cursor = i + len(needle)
        self.last_t = self.words[self.owner[i]]["start"]
        return self.last_t


def build_phrases(words: list[dict], max_words: int = 8) -> list[dict]:
    phrases, cur = [], []
    for idx, w in enumerate(words):
        cur.append(idx)
        scene_end = idx + 1 < len(words) and words[idx + 1]["scene"] != w["scene"]
        if w["brk"] or len(cur) >= max_words or scene_end or idx == len(words) - 1:
            phrases.append(cur)
            cur = []
    # gộp cụm quá ngắn (1 từ) vào cụm trước cho đỡ giật
    merged = []
    for p in phrases:
        if merged and len(p) == 1 and words[p[0]]["scene"] == words[merged[-1][-1]]["scene"] and len(merged[-1]) < max_words:
            merged[-1].extend(p)
        else:
            merged.append(p)
    return [{"from": p[0], "to": p[-1], "start": words[p[0]]["start"], "end": words[p[-1]]["end"]} for p in merged]


def build_timeline(spec: dict) -> tuple[dict, list[tuple[Path, float, float]]]:
    t = 0.0
    scenes, all_words, audio_parts = [], [], []
    for i, sc in enumerate(spec["scenes"]):
        mp3, words, dur = synthesize(sc["say"])
        attach_punctuation(sc["say"], words)
        lead = FIRST_LEAD if i == 0 else LEAD
        start, audio_at = t, t + lead
        end = audio_at + dur + GAP + (TAIL if i == len(spec["scenes"]) - 1 else 0)
        abs_words = [dict(w, start=w["start"] + audio_at, end=w["end"] + audio_at, scene=i) for w in words]
        cues = CueFinder(abs_words, f"{i + 1} ({sc['type']})")

        out = {k: v for k, v in sc.items() if k not in ("say", "events", "chips", "answer_cue")}
        out.update(start=round(start, 3), end=round(end, 3))
        if sc["type"] == "diagram":
            out["events"] = [dict({k: v for k, v in ev.items() if k != "cue"}, t=cues.time_of(ev["cue"])) for ev in sc.get("events", [])]
        if sc.get("chips"):
            out["chips"] = [dict(text=c["text"], t=cues.time_of(c["cue"]) if c.get("cue") else None) for c in sc["chips"]]
        if sc["type"] == "tip":
            out["answer_t"] = cues.time_of(sc.get("answer_cue", "đáp án"))
        scenes.append(out)
        all_words.extend(abs_words)
        audio_parts.append((mp3, audio_at - start, end - start))
        t = end

    data = {
        "meta": {"series": "AWS SAA-C03", "ep": spec["ep"], "total": 31, "title": spec["title"]},
        "duration": round(t, 3),
        "scenes": scenes,
        "words": [{"display": w["display"], "start": round(w["start"], 3), "end": round(w["end"], 3)} for w in all_words],
        "phrases": build_phrases(all_words),
        "diagrams": spec.get("diagrams", {}),
    }
    return data, audio_parts


def build_audio(parts: list[tuple[Path, float, float]], out_wav: Path) -> None:
    cmd = ["ffmpeg", "-v", "error", "-y"]
    filters = []
    for i, (mp3, delay, dur) in enumerate(parts):
        cmd += ["-i", str(mp3)]
        ms = int(round(delay * 1000))
        filters.append(f"[{i}:a]aresample=48000,adelay=delays={ms}:all=1,apad=whole_dur={dur:.3f},atrim=0:{dur:.3f}[a{i}]")
    filters.append("".join(f"[a{i}]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=0:a=1,loudnorm=I=-16:TP=-1.5[out]")
    cmd += ["-filter_complex", ";".join(filters), "-map", "[out]", "-ac", "2", str(out_wav)]
    subprocess.run(cmd, check=True)


def open_page(pw, data: dict):
    from factory.config import CHROME
    browser = pw.chromium.launch(executable_path=str(CHROME))
    page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
    page.goto(TEMPLATE.as_uri())
    page.evaluate("d => setup(d)", data)
    page.evaluate("Promise.all([document.fonts.load('700 40px BVP'), document.fonts.load('500 40px BVP')])")
    return browser, page


def render_segment(args: tuple) -> str:
    data, first, last, seg_path = args
    from playwright.sync_api import sync_playwright

    ff = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "mjpeg", "-i", "-",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS), seg_path],
        stdin=subprocess.PIPE,
    )
    with sync_playwright() as pw:
        browser, page = open_page(pw, data)
        # render lùi vài khung trước đoạn để trạng thái phụ đề/lớp được dựng sẵn
        page.evaluate("t => renderAt(t)", max(0, first - 1) / FPS)
        for i in range(first, last):
            page.evaluate("t => renderAt(t)", i / FPS)
            ff.stdin.write(page.screenshot(type="jpeg", quality=93))
        browser.close()
    ff.stdin.close()
    if ff.wait() != 0:
        raise RuntimeError(f"ffmpeg lỗi khi ghi {seg_path}")
    return seg_path


def safe_name(text: str) -> str:
    return re.sub(r'[<>:"/\\|?*]+', " -", text).strip()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Render một tập AWS SAA dạng motion graphics")
    ap.add_argument("ep", type=int)
    ap.add_argument("--preview", help="danh sách giây cần chụp PNG, ví dụ 3,12.5,30")
    ap.add_argument("--workers", type=int, default=WORKERS)
    args = ap.parse_args()

    spec_path = HERE / "scenes" / f"ep{args.ep:02d}.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    t0 = time.time()
    print(f"Tập {args.ep}: tạo giọng đọc cho {len(spec['scenes'])} cảnh...", flush=True)
    data, audio_parts = build_timeline(spec)
    print(f"  thời lượng {data['duration']:.1f}s, {len(data['words'])} từ", flush=True)

    if args.preview:
        from playwright.sync_api import sync_playwright

        PREVIEW_DIR.mkdir(exist_ok=True)
        with sync_playwright() as pw:
            browser, page = open_page(pw, data)
            for s in args.preview.split(","):
                t = float(s)
                page.evaluate("t => renderAt(t)", t)
                out = PREVIEW_DIR / f"ep{args.ep:02d}_{t:05.1f}.png"
                page.screenshot(path=str(out))
                print(f"  {out}")
            browser.close()
        return 0

    OUT_DIR.mkdir(exist_ok=True)
    total = math.ceil(data["duration"] * FPS)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        wav = tmp / "audio.wav"
        build_audio(audio_parts, wav)
        n = max(1, args.workers)
        bounds = [round(total * k / n) for k in range(n + 1)]
        jobs = [(data, bounds[k], bounds[k + 1], str(tmp / f"seg{k}.mp4")) for k in range(n) if bounds[k] < bounds[k + 1]]
        print(f"  render {total} khung hình bằng {len(jobs)} tiến trình...", flush=True)
        with ProcessPoolExecutor(max_workers=len(jobs)) as pool:
            segs = list(pool.map(render_segment, jobs))
        listing = tmp / "list.txt"
        listing.write_text("".join(f"file '{Path(s).as_posix()}'\n" for s in segs), encoding="utf-8")
        out = OUT_DIR / f"Tap-{args.ep:02d} - {safe_name(spec['title'])}.mp4"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-i", str(wav),
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out)],
            check=True,
        )
    print(f"XONG {out} ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
