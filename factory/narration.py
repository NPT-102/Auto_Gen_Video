"""Giọng đọc Edge/VieNeu có mốc từng từ, và dòng thời gian cảnh dùng chung cho các engine.

build_timeline(spec) trả về `data` (cảnh + thời điểm bắt đầu/kết thúc + mọi cue đã quy ra giây,
từ và cụm phụ đề) và các đoạn audio; build_audio() ghép thành một file wav.
"""

import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import unicodedata
import uuid
from pathlib import Path

from .config import CACHE_DIR
from .spec import Spec

TTS_CACHE = CACHE_DIR / "tts"
RATE = "+0%"
FIRST_LEAD = 0.25  # giọng vào gần như ngay: móc câu trong giây đầu
LEAD = 0.15
GAP = 0.4
TAIL = 1.2
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


_key_locks: dict[str, threading.Lock] = {}
_key_locks_guard = threading.Lock()


def synthesize(text: str, voice: str, rate: str = RATE) -> tuple[Path, list[dict], float]:
    """Edge TTS (có cache): trả về (mp3, [{text,start,end}], thời lượng giây).

    Nhiều engine chạy song song có thể xin cùng một câu: mỗi câu có khoá riêng để lượt sau chờ lượt đầu
    rồi dùng lại cache, và mỗi lần ghi dùng file tạm riêng (Windows không cho hai tiến trình cùng ghi một file)."""
    TTS_CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{voice}|{rate}|{text}".encode()).hexdigest()[:16]
    with _key_locks_guard:
        lock = _key_locks.setdefault(key, threading.Lock())
    with lock:
        mp3, meta = TTS_CACHE / f"{key}.mp3", TTS_CACHE / f"{key}.json"
        if mp3.exists() and meta.exists():
            return mp3, json.loads(meta.read_text(encoding="utf-8")), probe_duration(mp3)
        return _synthesize_uncached(text, voice, rate, mp3, meta)


def synthesize_spec(text: str, spec: Spec) -> tuple[Path, list[dict], float]:
    """Giọng đã chọn trong kịch bản; giữ nguyên cache và giọng Edge cho kịch bản cũ."""
    if spec.tts_provider == "vieneu":
        from .vieneu import synthesize as vieneu_synthesize

        return vieneu_synthesize(text, spec.vieneu_voice)
    return synthesize(text, spec.voice)


async def _stream_to_file(text: str, voice: str, rate: str, path: Path) -> tuple[list[dict], int]:
    import edge_tts

    words = []
    comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary", receive_timeout=60)
    written = 0
    with open(path, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
                written += len(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                words.append({"text": chunk["text"], "start": start, "end": start + chunk["duration"] / 1e7})
    return words, written


def _tts_chunks(text: str, max_chars: int = 260) -> list[str]:
    """Split a failed long TTS request at sentence or word boundaries."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?…;:])\s+", text.strip()) if s.strip()]
    chunks: list[str] = []
    current = ""
    for sentence in sentences or [text.strip()]:
        pieces: list[str] = []
        piece = ""
        for word in sentence.split():
            candidate = f"{piece} {word}".strip()
            if piece and len(candidate) > max_chars:
                pieces.append(piece)
                piece = word
            else:
                piece = candidate
        if piece:
            pieces.append(piece)
        for piece in pieces:
            candidate = f"{current} {piece}".strip()
            if current and len(candidate) > max_chars:
                chunks.append(current)
                current = piece
            else:
                current = candidate
    if current:
        chunks.append(current)
    return chunks


def _synthesize_uncached(text: str, voice: str, rate: str, mp3: Path, meta: Path) -> tuple[Path, list[dict], float]:
    # Edge can occasionally complete a WebSocket request without sending audio.
    # Keep retries short, then retry sentence-sized requests before failing the job.
    def request(part: str, target: Path, retries: int) -> tuple[list[dict] | None, object | None]:
        last_error: object | None = None
        limit = 30 + len(part) * 0.12
        for attempt in range(retries):
            target.unlink(missing_ok=True)
            try:
                words, audio_bytes = asyncio.run(asyncio.wait_for(
                    _stream_to_file(part, voice, rate, target), timeout=limit,
                ))
                # Word boundaries are needed for captions, and an empty MP3 is unusable.
                if words and audio_bytes > 1024:
                    return words, None
                last_error = "Edge returned no audio or no word timings"
            except asyncio.TimeoutError:
                last_error = f"Edge did not respond within {limit:.0f}s"
            except Exception as exc:
                last_error = exc
            target.unlink(missing_ok=True)
            if attempt + 1 < retries:
                time.sleep(2 * (attempt + 1))
        return None, last_error

    tmp = mp3.with_name(f"{mp3.stem}.{uuid.uuid4().hex[:8]}.part.mp3")
    words, last_error = request(text, tmp, retries=3)
    if words is not None:
        meta_tmp = meta.with_name(f"{meta.stem}.{uuid.uuid4().hex[:8]}.part")
        try:
            os.replace(tmp, mp3)
            meta_tmp.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
            os.replace(meta_tmp, meta)
            return mp3, words, probe_duration(mp3)
        finally:
            tmp.unlink(missing_ok=True)
            meta_tmp.unlink(missing_ok=True)

    # A troublesome full scene often works when Edge receives its sentences separately.
    chunks = _tts_chunks(text)
    if len(chunks) > 1:
        part_files: list[Path] = []
        all_words: list[dict] = []
        offset = 0.0
        listing: Path | None = None
        merged: Path | None = None
        meta_tmp: Path | None = None
        try:
            for index, chunk in enumerate(chunks):
                part = mp3.with_name(f"{mp3.stem}.{uuid.uuid4().hex[:8]}.{index}.part.mp3")
                part_files.append(part)
                chunk_words, chunk_error = request(chunk, part, retries=3)
                if chunk_words is None:
                    last_error = chunk_error
                    raise RuntimeError("A sentence-sized Edge request also failed")
                duration = probe_duration(part)
                all_words.extend(
                    {**word, "start": word["start"] + offset, "end": word["end"] + offset}
                    for word in chunk_words
                )
                offset += duration

            listing = mp3.with_name(f"{mp3.stem}.{uuid.uuid4().hex[:8]}.concat.txt")
            merged = mp3.with_name(f"{mp3.stem}.{uuid.uuid4().hex[:8]}.part.mp3")
            # The generated files sit beside the list, so ffmpeg never has to parse
            # the workspace path that contains spaces.
            listing.write_text("".join(f"file '{file.name}'\n" for file in part_files), encoding="utf-8")
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                 "-c:a", "libmp3lame", "-b:a", "128k", str(merged)],
                check=True, timeout=120,
            )
            meta_tmp = meta.with_name(f"{meta.stem}.{uuid.uuid4().hex[:8]}.part")
            meta_tmp.write_text(json.dumps(all_words, ensure_ascii=False), encoding="utf-8")
            os.replace(merged, mp3)
            os.replace(meta_tmp, meta)
            return mp3, all_words, probe_duration(mp3)
        except RuntimeError:
            pass
        finally:
            for part in part_files:
                part.unlink(missing_ok=True)
            if listing:
                listing.unlink(missing_ok=True)
            if merged:
                merged.unlink(missing_ok=True)
            if meta_tmp:
                meta_tmp.unlink(missing_ok=True)

    raise RuntimeError(f"Edge TTS lỗi: {text[:60]}...: {last_error}")

def attach_punctuation(text: str, words: list[dict]) -> None:
    pos, low = 0, text.lower()
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
    """Quy cụm từ trong lời đọc ra thời điểm; tìm tuần tự để cụm lặp lại không bị nhầm."""

    def __init__(self, words: list[dict], label: str, log=print):
        self.words, self.label, self.log = words, label, log
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
        if not needle:   # không có cue: hiện ngay khi cảnh bắt đầu đọc
            return self.words[0]["start"] if self.words else self.last_t
        i = self.joined.find(needle, self.cursor)
        if i < 0:
            i = self.joined.find(needle)
        if i < 0 or not needle:
            self.log(f"  ! không thấy cue '{cue}' trong cảnh {self.label}, dùng thời điểm ước lượng")
            self.last_t += 0.8
            return self.last_t
        self.cursor = i + len(needle)
        self.last_t = self.words[self.owner[i]]["start"]
        return self.last_t


# Hình hiện sớm hơn chữ được đọc một nhịp: hiện đúng lúc đọc thì mắt thấy hình chậm hơn tai nghe (người xem góp ý
# "hình hiện chậm so với nội dung kể").
REVEAL_LEAD = 0.3


def _resolve_cues(node, cues: CueFinder, floor: float = 0.0):
    """Mọi dict có khoá 'cue' được gắn thêm 't' (giây tuyệt đối, sớm hơn lời REVEAL_LEAD, không trước `floor`)."""
    if isinstance(node, dict):
        if isinstance(node.get("cue"), str):
            node["t"] = round(max(cues.time_of(node["cue"]) - REVEAL_LEAD, floor), 3)
        for k, v in node.items():
            if k != "cue":
                _resolve_cues(v, cues, floor)
    elif isinstance(node, list):
        for v in node:
            _resolve_cues(v, cues, floor)


def build_phrases(words: list[dict], max_words: int = 8) -> list[dict]:
    phrases, cur = [], []
    for idx, w in enumerate(words):
        cur.append(idx)
        scene_end = idx + 1 < len(words) and words[idx + 1]["scene"] != w["scene"]
        if w["brk"] or len(cur) >= max_words or scene_end or idx == len(words) - 1:
            phrases.append(cur)
            cur = []
    merged = []
    for p in phrases:
        if merged and len(p) == 1 and words[p[0]]["scene"] == words[merged[-1][-1]]["scene"] and len(merged[-1]) < max_words:
            merged[-1].extend(p)
        else:
            merged.append(p)
    return [{"from": p[0], "to": p[-1], "start": words[p[0]]["start"], "end": words[p[-1]]["end"]} for p in merged]


def build_timeline(spec: Spec, log=print) -> tuple[dict, list[tuple[Path, float, float]]]:
    from .flow import compile_flows

    compiled = compile_flows(spec.dump())      # cảnh flow → cảnh diagram có toạ độ (ELK)
    t = 0.0
    scenes, all_words, audio_parts = [], [], []
    n = len(compiled["scenes"])
    for i, sc in enumerate(compiled["scenes"]):
        mp3, words, dur = synthesize_spec(sc["say"], spec)
        attach_punctuation(sc["say"], words)
        lead = FIRST_LEAD if i == 0 else LEAD
        start, audio_at = t, t + lead
        end = audio_at + dur + GAP + (TAIL if i == n - 1 else 0)
        abs_words = [dict(w, start=w["start"] + audio_at, end=w["end"] + audio_at, scene=i) for w in words]
        cues = CueFinder(abs_words, f"{i + 1} ({sc['type']})", log)
        out = {k: v for k, v in sc.items() if k != "say"}
        _resolve_cues(out, cues, start + 0.1)
        if sc["type"] == "tip":
            out["answer_t"] = round(max(cues.time_of(sc.get("answer_cue", "đáp án")) - REVEAL_LEAD, start + 0.1), 3)
        out.update(start=round(start, 3), end=round(end, 3), audio_at=round(audio_at, 3))
        scenes.append(out)
        all_words.extend(abs_words)
        audio_parts.append((mp3, audio_at - start, end - start))
        t = end

    data = {
        "meta": {"series": spec.series or "", "ep": spec.ep, "total": spec.total, "title": spec.title},
        "duration": round(t, 3),
        "scenes": scenes,
        "words": [{"display": w["display"], "start": round(w["start"], 3), "end": round(w["end"], 3)} for w in all_words],
        "phrases": build_phrases(all_words),
        "diagrams": compiled["diagrams"],
    }
    return data, audio_parts


SFX_DIR = CACHE_DIR / "sfx"
MUSIC_DIR = CACHE_DIR.parent / "assets" / "music"   # bỏ nhạc nền (mp3/wav/m4a) có bản quyền dùng được vào đây


def _sfx_files() -> dict[str, Path]:
    """Hiệu ứng âm thanh tự tổng hợp bằng ffmpeg (không vướng bản quyền)."""
    SFX_DIR.mkdir(parents=True, exist_ok=True)
    recipes = {
        "pop": ["-f", "lavfi", "-i", "aevalsrc=exprs='0.5*sin(2*PI*(520+1900*t)*t)*exp(-34*t)':s=48000:d=0.18"],
        "whoosh": ["-f", "lavfi", "-i", "anoisesrc=d=0.55:c=pink:r=48000:a=0.6",
                   "-af", "highpass=f=250,lowpass=f=4500,afade=t=in:d=0.25,afade=t=out:st=0.27:d=0.28"],
    }
    out = {}
    for name, args in recipes.items():
        f = SFX_DIR / f"{name}.wav"
        if not f.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", *args, "-ac", "1", str(f)], check=True)
        out[name] = f
    return out


def sfx_events(data: dict) -> list[tuple[float, str]]:
    """Whoosh khi chuyển cảnh, pop khi một thành phần hiện ra; cách nhau tối thiểu 0,35 giây."""
    ev = []
    for i, s in enumerate(data["scenes"]):
        if i > 0:
            ev.append((s["start"], "whoosh"))
        typ, st = s["type"], s["start"]
        if typ == "title":
            times = [c.get("t") for c in s.get("chips", []) or []]
        elif typ == "bullets":
            times = [it.get("t", st + 0.5 + k * 0.9) for k, it in enumerate(s.get("items", []))]
        elif typ == "stat":
            times = [x.get("t", st + 0.5 + k * 0.9) for k, x in enumerate(s.get("stats", []))]
        elif typ == "compare":
            times = [(s.get("left") or {}).get("t", st + 0.4), (s.get("right") or {}).get("t")]
        elif typ == "diagram":
            times = [e.get("t") for e in s.get("events", []) if e.get("show")]
        elif typ == "tip":
            times = [s.get("answer_t")]
        else:
            times = []
        ev += [(t, "pop") for t in times if t]
    ev.sort()
    out, last = [], -9.0
    for t, kind in ev:
        if t - last >= 0.35:
            out.append((round(t, 3), kind))
            last = t
    return out[:90]


def build_audio(parts: list[tuple[Path, float, float]], out_wav: Path, data: dict | None = None, title: str = "") -> None:
    """Ghép giọng các cảnh; có `data` thì thêm hiệu ứng âm thanh, có nhạc trong assets/music thì thêm nhạc nền tự hạ khi có giọng."""
    cmd = ["ffmpeg", "-v", "error", "-y"]
    filters = []
    for i, (mp3, delay, dur) in enumerate(parts):
        cmd += ["-i", str(mp3)]
        ms = int(round(delay * 1000))
        filters.append(f"[{i}:a]aresample=48000,adelay=delays={ms}:all=1,apad=whole_dur={dur:.3f},atrim=0:{dur:.3f}[a{i}]")
    total = sum(p[2] for p in parts)
    filters.append("".join(f"[a{i}]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=0:a=1[voice]")
    n_in = len(parts)
    mix = ["[vmain]"]

    tracks = sorted(MUSIC_DIR.glob("*.mp3")) + sorted(MUSIC_DIR.glob("*.wav")) + sorted(MUSIC_DIR.glob("*.m4a")) if MUSIC_DIR.exists() else []
    if tracks:
        track = tracks[int(hashlib.sha1(title.encode()).hexdigest(), 16) % len(tracks)]
        cmd += ["-stream_loop", "-1", "-i", str(track)]
        filters.append("[voice]asplit=2[vmain][vkey]")
        filters.append(f"[{n_in}:a]aresample=48000,atrim=0:{total:.3f},volume=0.14,afade=t=out:st={max(0, total - 2):.3f}:d=2[mus]")
        filters.append("[mus][vkey]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=400[duck]")
        mix.append("[duck]")
        n_in += 1
    else:
        filters.append("[voice]anull[vmain]")

    events = sfx_events(data) if data else []
    if events:
        files = _sfx_files()
        for kind, vol in (("pop", 0.32), ("whoosh", 0.26)):
            times = [t for t, k in events if k == kind]
            if not times:
                continue
            cmd += ["-i", str(files[kind])]
            filters.append(f"[{n_in}:a]aresample=48000,volume={vol},asplit={len(times)}" + "".join(f"[{kind}{j}]" for j in range(len(times))))
            for j, t in enumerate(times):
                ms = max(0, int(round(t * 1000)) - (60 if kind == "whoosh" else 0))
                filters.append(f"[{kind}{j}]adelay=delays={ms}:all=1[{kind}d{j}]")
                mix.append(f"[{kind}d{j}]")
            n_in += 1

    filters.append("".join(mix) + f"amix=inputs={len(mix)}:normalize=0:duration=first,atrim=0:{total:.3f},loudnorm=I=-16:TP=-1.5[out]")
    cmd += ["-filter_complex", ";".join(filters), "-map", "[out]", "-ac", "2", "-ar", "48000", str(out_wav)]  # loudnorm tự nâng lên 192 kHz
    subprocess.run(cmd, check=True)


if __name__ == "__main__":  # thử nhanh: python -m factory.narration content/aws-saa/ep05.json
    from .spec import load_spec

    sys.stdout.reconfigure(encoding="utf-8")
    d, _ = build_timeline(load_spec(Path(sys.argv[1])))
    print(f"{d['duration']:.1f}s, {len(d['scenes'])} cảnh, {len(d['words'])} từ")
