"""Giọng ElevenLabs cho bản podcast của MoneyPrinterTurbo: trả mp3 kèm mốc thời gian từng từ (phụ đề karaoke).

- Key: ELEVENLABS_API_KEY trong môi trường hoặc video-factory/.env (người dùng tự dán).
- Model eleven_flash_v2_5: model hiện hành duy nhất của ElevenLabs đọc được tiếng Việt
  (eleven_v3 và eleven_multilingual_v2 không có tiếng Việt).
- Giọng lấy từ thư viện giọng (Voice Library). Giọng thư viện phải nằm trong "My Voices" của tài khoản mới gọi
  API được, nên lần đầu dùng engine tự thêm vào. Gói Free KHÔNG gọi được giọng thư viện qua API (HTTP 402, kể cả giọng
  có free_users_allowed) — cần gói Starter trở lên.
"""

import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path

import httpx

from .config import CACHE_DIR, _read_dotenv

API = "https://api.elevenlabs.io/v1"
MODEL = "eleven_flash_v2_5"
VOICES = {   # khoá → (voice_id trong thư viện, tên hiển thị, tên để tìm trong thư viện)
    "mai": ("d5HVupAWCwe4e6GvMCAL", "Mai · nữ, giọng Hà Nội", "Mai"),
    "nhatphong": ("6adFm46eyy74snVn6YrT", "Nhật Phong · nam, dẫn chuyện", "Nhật Phong"),
}
DEFAULT_VOICE = "mai"
# Hơi thả lỏng để có cảm xúc kiểu tâm sự; nhanh hơn một chút vì người thật nói ~210 tiếng/phút
SETTINGS = {"stability": 0.4, "similarity_boost": 0.8, "style": 0.3, "speed": 1.05, "use_speaker_boost": True}
CACHE = CACHE_DIR / "eleven"
PUNCT = ".,!?…;:"


class ElevenError(RuntimeError):
    pass


def api_key() -> str | None:
    return os.environ.get("ELEVENLABS_API_KEY") or _read_dotenv().get("ELEVENLABS_API_KEY") or None


def voices() -> list[dict]:
    return [{"key": k, "label": v[1]} for k, v in VOICES.items()]


def _resolve(voice: str | None) -> tuple[str, str]:
    """(voice_id, tên để tìm). Nhận khoá trong VOICES hoặc dán thẳng một voice_id khác."""
    voice = (voice or os.environ.get("ELEVENLABS_VOICE") or _read_dotenv().get("ELEVENLABS_VOICE") or DEFAULT_VOICE).strip()
    vid, _, name = VOICES.get(voice, (voice, voice, ""))
    return vid, name


def _explain(r: httpx.Response) -> str:
    try:
        detail = r.json().get("detail")
        detail = detail.get("message") or detail.get("status") if isinstance(detail, dict) else detail
    except ValueError:
        detail = r.text[:200]
    hints = {401: "key ElevenLabs sai hoặc đã bị thu hồi", 402: "cần gói trả phí cho giọng/tính năng này",
             403: "tài khoản không được dùng giọng này qua API (gói miễn phí có thể không dùng được giọng thư viện)",
             429: "hết hạn mức ký tự hoặc gọi quá nhanh"}
    return f"ElevenLabs HTTP {r.status_code}: {hints.get(r.status_code, '')} ({detail})"


def _library_voice(vid: str, name: str, key: str, log) -> str:
    """Đảm bảo giọng có trong "My Voices"; trả về voice_id dùng được để đọc."""
    added_file = CACHE / "added.json"
    added = json.loads(added_file.read_text(encoding="utf-8")) if added_file.exists() else {}
    if vid in added:
        return added[vid]
    h = {"xi-api-key": key}
    if httpx.get(f"{API}/voices/{vid}", headers=h, timeout=30).status_code == 200:
        mine = vid
    else:
        log(f"thêm giọng '{name or vid}' từ thư viện vào tài khoản ElevenLabs")
        r = httpx.get(f"{API}/shared-voices", headers=h, params={"search": name or vid, "page_size": 50}, timeout=30)
        if r.status_code != 200:
            raise ElevenError(_explain(r))
        owner = next((v.get("public_owner_id") for v in r.json().get("voices", []) if v.get("voice_id") == vid), None)
        if not owner:
            raise ElevenError(f"không tìm thấy giọng {vid} trong thư viện ElevenLabs")
        r = httpx.post(f"{API}/voices/add/{owner}/{vid}", headers=h, json={"new_name": f"{name or vid} (video-factory)"}, timeout=30)
        if r.status_code != 200:
            raise ElevenError(_explain(r))
        mine = r.json().get("voice_id") or vid
    added[vid] = mine
    added_file.parent.mkdir(parents=True, exist_ok=True)
    added_file.write_text(json.dumps(added), encoding="utf-8")
    return mine


def _words(alignment: dict) -> list[dict]:
    """Mốc từng ký tự → mốc từng từ (tách theo khoảng trắng), giữ dấu câu để hiển thị và ngắt cụm."""
    words, cur, start, end = [], "", 0.0, 0.0
    for ch, a, b in zip(alignment["characters"], alignment["character_start_times_seconds"],
                        alignment["character_end_times_seconds"]):
        if ch.isspace():
            if cur:
                words.append({"text": cur, "start": start, "end": end})
                cur = ""
            continue
        if not cur:
            start = a
        cur, end = cur + ch, b
    if cur:
        words.append({"text": cur, "start": start, "end": end})
    for w in words:
        w["display"], w["brk"] = w["text"], w["text"][-1] in PUNCT
    return words


def synthesize(text: str, voice: str | None = None, log=print) -> tuple[Path, list[dict], float]:
    """Đọc cả đoạn trong một lần gọi. Trả (file mp3, các từ có mốc thời gian, thời lượng giây); có cache."""
    key = api_key()
    if not key:
        raise ElevenError("chưa có ELEVENLABS_API_KEY trong video-factory/.env")
    vid, name = _resolve(voice)
    h = hashlib.sha1(json.dumps([text, vid, MODEL, SETTINGS], ensure_ascii=False).encode()).hexdigest()[:16]
    mp3, meta = CACHE / f"{h}.mp3", CACHE / f"{h}.json"
    if mp3.exists() and meta.exists():
        data = json.loads(meta.read_text(encoding="utf-8"))
        return mp3, data["words"], data["duration"]
    use_id = _library_voice(vid, name, key, log)
    log(f"ElevenLabs đọc {len(text)} ký tự bằng giọng {name or vid}")
    r = httpx.post(f"{API}/text-to-speech/{use_id}/with-timestamps", params={"output_format": "mp3_44100_128"},
                   headers={"xi-api-key": key},
                   json={"text": text, "model_id": MODEL, "language_code": "vi", "voice_settings": SETTINGS}, timeout=300)
    if r.status_code != 200:
        raise ElevenError(_explain(r))
    body = r.json()
    CACHE.mkdir(parents=True, exist_ok=True)
    mp3.write_bytes(base64.b64decode(body["audio_base64"]))
    words = _words(body.get("alignment") or body.get("normalized_alignment") or {"characters": [], "character_start_times_seconds": [], "character_end_times_seconds": []})
    duration = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp3)],
                                    capture_output=True, text=True).stdout.strip() or 0)
    meta.write_text(json.dumps({"words": words, "duration": duration}, ensure_ascii=False), encoding="utf-8")
    return mp3, words, duration
