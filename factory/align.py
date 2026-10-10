"""Mốc thời gian từng chữ cho file giọng có sẵn (tải từ web ElevenLabs, tự thu âm…) để làm phụ đề karaoke.

Whisper (faster-whisper có sẵn trong venv của MoneyPrinterTurbo) nghe lại file, rồi khớp với lời thoại đã biết:
chữ khớp lấy đúng mốc Whisper nghe được, chữ Whisper nghe sai thì nội suy giữa hai chữ khớp gần nhất.
Hiển thị luôn là lời thoại gốc (đúng chính tả), Whisper chỉ dùng để lấy thời điểm.
"""

import difflib
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from .config import CACHE_DIR, MPT_DIR, setting
from .pyrun import venv_python
from .narration import PUNCT, norm

MODEL = "small"          # đủ để lấy mốc thời gian; lời hiển thị lấy từ kịch bản nên không cần model lớn
CACHE = CACHE_DIR / "align"
WHISPER = r"""
import json, sys
from faster_whisper import WhisperModel
model = WhisperModel(sys.argv[2], device="cpu", compute_type="int8")
segments, info = model.transcribe(sys.argv[1], language="vi", word_timestamps=True)
words = [{"w": w.word.strip(), "a": w.start, "b": w.end} for s in segments for w in (s.words or [])]
print(json.dumps({"words": words, "duration": info.duration}))
"""


def whisper_words(audio: Path) -> tuple[list[dict], float]:
    h = hashlib.sha1(audio.read_bytes()).hexdigest()[:16]
    f = CACHE / f"{h}-{MODEL}.json"
    if not f.exists():
        # A dedicated interpreter can be configured for standalone VieNeu use.
        # Prefer MPT's existing Whisper installation; otherwise use the factory environment.
        python = setting("ALIGN_PYTHON")
        if python:
            command = (python,)
        elif (MPT_DIR / ".venv" / "pyvenv.cfg").exists():
            venv = MPT_DIR / ".venv"
            command = venv_python(venv)
        elif (Path(sys.prefix) / "pyvenv.cfg").exists():
            # pyrun.py injects the venv into a base interpreter. Reuse its bootstrap
            # so a child process sees the same site-packages on Windows.
            venv = Path(sys.prefix)
            command = venv_python(venv)
        else:
            command = (sys.executable,)
        p = subprocess.run([*command, "-c", WHISPER, str(audio), MODEL], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=1800)
        lines = [l for l in p.stdout.splitlines() if l.startswith("{")]
        if p.returncode != 0 or not lines:
            raise RuntimeError("Whisper không đọc được file giọng. Cài faster-whisper vào môi trường Python "
                               "của factory hoặc đặt ALIGN_PYTHON tới Python đã cài faster-whisper: "
                               f"{(p.stderr or p.stdout)[-300:]}")
        CACHE.mkdir(parents=True, exist_ok=True)
        f.write_text(lines[-1], encoding="utf-8")
    data = json.loads(f.read_text(encoding="utf-8"))
    return data["words"], float(data["duration"])


def align(audio: Path, text: str, log=print) -> tuple[list[dict], float]:
    """(các chữ của lời thoại kèm start/end/display/brk, thời lượng file)."""
    heard, duration = whisper_words(audio)
    tokens = text.split()
    a = [norm(t) for t in tokens]
    b = [norm(w["w"]) for w in heard]
    times: list[tuple[float, float] | None] = [None] * len(tokens)
    for i, j, size in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_matching_blocks():
        for k in range(size):
            times[i + k] = (heard[j + k]["a"], heard[j + k]["b"])
    matched = sum(t is not None for t in times)
    log(f"Whisper khớp {matched}/{len(tokens)} chữ với lời thoại; phần còn lại nội suy")
    if not matched:
        raise RuntimeError("file giọng không khớp lời thoại (có đúng file không?)")
    k = 0
    while k < len(tokens):          # nội suy các đoạn chữ Whisper nghe sai / bỏ sót
        if times[k] is not None:
            k += 1
            continue
        end = k
        while end < len(tokens) and times[end] is None:
            end += 1
        t0 = times[k - 1][1] if k > 0 else 0.0
        t1 = times[end][0] if end < len(tokens) else duration
        step = max(t1 - t0, 0.01) / (end - k)
        for m in range(k, end):
            times[m] = (t0 + step * (m - k), t0 + step * (m - k + 1))
        k = end
    return [{"text": t, "display": t, "brk": t[-1] in PUNCT, "start": s, "end": e}
            for t, (s, e) in zip(tokens, times)], duration
