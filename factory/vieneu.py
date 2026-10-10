"""VieNeu-TTS v3 Turbo speech API → MP3 + Whisper word timings.

Run VieNeu separately (CPU or GPU); the factory needs no VieNeu model dependencies.
API contract: https://github.com/pnnbao97/VieNeu-TTS/blob/main/apps/openai_speech.py
"""

import hashlib
import json
import os
import subprocess
import threading
import uuid
from pathlib import Path

import httpx

from .config import CACHE_DIR, setting
from .narration import probe_duration

TTS_CACHE = CACHE_DIR / "vieneu"
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def base_url() -> str:
    return setting("VIENEU_URL", "http://127.0.0.1:8000").rstrip("/")


def default_voice() -> str:
    return setting("VIENEU_VOICE", "Hải Đăng")


def _headers() -> dict[str, str]:
    key = setting("VIENEU_API_KEY")
    return {"Authorization": f"Bearer {key}"} if key else {}


def _endpoint(base: str, path: str) -> str:
    return f"{base}{'' if base.endswith('/v1') else '/v1'}/{path}"


def voices() -> list[dict]:
    """Discover presets (including voices registered in the local server)."""
    try:
        with httpx.Client(timeout=5, trust_env=False) as client:
            response = client.get(_endpoint(base_url(), "voices"), headers=_headers())
            response.raise_for_status()
        return [{"key": v["id"], "label": v.get("name") or v["id"]} for v in response.json()["data"]]
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("Không lấy được giọng VieNeu: kiểm tra server, VIENEU_URL và VIENEU_API_KEY.") from exc


def synthesize(text: str, voice: str | None = None) -> tuple[Path, list[dict], float]:
    from .align import align

    voice = voice or default_voice()
    base = base_url()
    model = "vieneu-v3-turbo"
    key = hashlib.sha1(json.dumps([base, model, voice, text, "pcm48k-align-v1"],
                                  ensure_ascii=False).encode()).hexdigest()[:16]
    TTS_CACHE.mkdir(parents=True, exist_ok=True)
    with _guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        mp3, meta = TTS_CACHE / f"{key}.mp3", TTS_CACHE / f"{key}.json"
        if mp3.exists() and meta.exists():
            return mp3, json.loads(meta.read_text(encoding="utf-8")), probe_duration(mp3)
        # PCM avoids the streaming WAV header's unknown length. All adapters consume MP3.
        try:
            with httpx.Client(timeout=httpx.Timeout(600, connect=10), trust_env=False) as client:
                response = client.post(_endpoint(base, "audio/speech"), headers=_headers(), json={
                    "model": model, "input": text, "voice": voice,
                    "response_format": "pcm", "sample_rate": 48000,
                })
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"VieNeu HTTP {exc.response.status_code}: kiểm tra giọng, key hoặc trạng thái server.") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError("VieNeu không phản hồi: bật speech API và kiểm tra VIENEU_URL.") from exc
        pcm = response.content
        if not pcm or len(pcm) % 2:
            raise RuntimeError("VieNeu trả về audio PCM rỗng hoặc không hợp lệ.")
        suffix = uuid.uuid4().hex[:8]
        tmp = mp3.with_name(f"{key}.{suffix}.part.mp3")
        meta_tmp = meta.with_name(f"{key}.{suffix}.part.json")
        try:
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "s16le", "-ar", "48000", "-ac", "1",
                            "-i", "pipe:0", "-c:a", "libmp3lame", "-b:a", "128k", str(tmp)],
                           input=pcm, capture_output=True, check=True, timeout=120)
            duration = probe_duration(tmp)
            words, _ = align(tmp, text)
            meta_tmp.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, mp3)
            os.replace(meta_tmp, meta)
            return mp3, words, duration
        finally:
            tmp.unlink(missing_ok=True)
            meta_tmp.unlink(missing_ok=True)
