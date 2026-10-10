"""MoneyPrinterTurbo: video stock từ Pexels + giọng Edge TTS + phụ đề (chạy cli.py chế độ batch).

Kịch bản có phần "podcast" (văn nói, Gemini viết thêm) thì bản này thành podcast tâm sự: đọc lời podcast, clip nền
theo từ khoá podcast. Nguồn giọng, theo thứ tự: file giọng làm sẵn (podcast.audio — tải từ web ElevenLabs hoặc tự thu,
Whisper căn mốc từng chữ) → VieNeu (nếu đã chọn) hoặc API ElevenLabs (cần gói trả phí cho giọng thư viện) → Edge mặc định.
Giọng được đưa vào MoneyPrinterTurbo dưới dạng custom_audio_file, phụ đề karaoke gắn sau.

Nhạc nền: KHÔNG dùng kho nhạc có sẵn của MoneyPrinterTurbo (resource/songs: 29 bản không rõ nguồn; 28/09 một bản
"Relaxing Peaceful Piano…" bị Content ID nhận, YouTube chặn Shorts toàn cầu). Chỉ trộn nhạc người dùng tự bỏ vào
assets/music/podcast/ (bản podcast) hoặc assets/music/ — MoneyPrinterTurbo chỉ nhận nhạc trong thư mục của nó nên
engine tự trộn, có hạ nhạc khi có giọng. Không có nhạc thì video chỉ có giọng (thêm nhạc trong trình đăng của nền tảng).

Ảnh vẽ trên máy thay cho clip Pexels: kịch bản đặt "image_source": "comfyui" (kèm "image_note" nếu cần, vd. chỉ thiên
nhiên, không người). Để hình đổi đúng lúc từng câu, engine tự tạo giọng đọc (Edge TTS, biết mốc từng từ), factory/beats.py
vẽ ảnh cho từng câu và dựng sẵn mỗi ảnh thành clip zoom dài đúng thời lượng câu; MoneyPrinterTurbo nhận giọng làm sẵn
(custom_audio_file) + các clip (chế độ "local" + "sequential", clip phải nằm trong storage/local_videos/ — nó chặn tư
liệu cục bộ ở chỗ khác) rồi ghép; phụ đề karaoke gắn sau. Bản 06/10 đầu tiên để MoneyPrinterTurbo tự cắt ảnh theo ô
4 giây và tự đọc giọng → hình lệch lời vài giây. Bản podcast vẫn dùng clip Pexels.
"""

import json
import random
import shutil
from pathlib import Path

from .. import align, eleven
from ..beats import _source as image_source, sentence_clips
from ..captions import esc, karaoke_ass
from ..config import CONTENT_DIR, ENGINES_DIR, MPT_DIR
from ..narration import MUSIC_DIR, attach_punctuation, synthesize_spec
from ..pyrun import python_path, venv_python
from ..spec import Spec
from .base import Engine, EngineError, Log, run

PYTHON = python_path(MPT_DIR / ".venv")
LOCAL = MPT_DIR / "storage" / "local_videos"   # MoneyPrinterTurbo chặn tư liệu cục bộ nằm ngoài thư mục này
FONTS = ENGINES_DIR / "hyperframes-academic" / "fonts"
PODCAST_MUSIC = MUSIC_DIR / "podcast"
LOUDNORM = "loudnorm=I=-14:TP=-1.5:LRA=11"   # độ to thường dùng cho video mạng xã hội

SETTINGS = {
    "video_source": "pexels",
    "video_aspect": "9:16",
    "video_concat_mode": "random",
    "video_clip_duration": 4,
    "video_language": "vi-VN",
    "voice_rate": 1.0,
    "voice_volume": 1.0,
    "bgm_type": "",          # không dùng kho nhạc của MoneyPrinterTurbo (dính bản quyền) — xem docstring
    "bgm_volume": 0.0,
    "subtitle_enabled": True,
    "subtitle_position": "bottom",
    "font_name": "BeVietnamPro-Bold.ttf",   # font mặc định của app thiếu dấu tiếng Việt
    "font_size": 60,
    "stroke_width": 2.0,
    "n_threads": 8,
}


def _music(podcast: bool) -> Path | None:
    """Nhạc người dùng tự bỏ vào (có quyền dùng): podcast ưu tiên assets/music/podcast/, sau đó assets/music/."""
    for folder in ([PODCAST_MUSIC] if podcast else []) + [MUSIC_DIR]:
        files = sorted(p for p in folder.glob("*") if p.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg"))
        if files:
            return random.choice(files)
    return None


class MoneyPrinterTurbo(Engine):
    key = "mpt"
    label = "MoneyPrinterTurbo"
    style = "Video stock Pexels (hoặc ảnh vẽ trên máy), phụ đề chạy dưới; có bản podcast thì đọc kiểu tâm sự"

    def check(self):
        if not PYTHON.exists():
            return False, f"chưa cài: chạy python3 cai-dat.py (không thấy {PYTHON})"
        return True, ""

    def render(self, spec: Spec, workdir: Path, log: Log) -> Path:
        pod = spec.podcast or {}
        voice = spec.voice if spec.voice.endswith(("-Female", "-Male")) else f"{spec.voice}-Female"
        subject = f"{spec.series} tập {spec.ep}: {spec.title}" if spec.series and spec.ep else spec.title
        task = {**SETTINGS, "voice_name": voice, "video_subject": pod.get("title") or subject,
                "video_script": pod.get("say") or spec.narration()}
        terms = pod.get("stock_terms") or spec.stock_terms
        if terms:
            task["video_terms"] = terms   # không có thì MoneyPrinterTurbo tự nhờ LLM đặt từ khoá

        words, music = None, None
        if pod:
            log(f"bản podcast: \"{pod.get('title', '')}\" ({len(pod['say'].split())} từ)")
            audio = Path(pod["audio"]) if pod.get("audio") else None
            if audio and not audio.is_absolute():
                audio = CONTENT_DIR / audio
            if audio and not audio.exists():
                log(f"không thấy file giọng {pod['audio']} → bỏ qua")
                audio = None
            if audio:   # file giọng làm sẵn (web ElevenLabs, tự thu…): Whisper căn mốc từng chữ cho phụ đề
                try:
                    words, dur = align.align(audio, pod["say"], log)
                    task.update(custom_audio_file=str(audio), subtitle_enabled=False)
                    log(f"dùng file giọng {audio.name} ({dur:.0f} giây)")
                except (RuntimeError, OSError) as exc:
                    log(f"không căn được file giọng ({exc}) → dùng provider {spec.tts_provider}")
                    words = None
            elif spec.tts_provider == "vieneu":
                log("bản podcast dùng giọng VieNeu đã chọn")
            elif eleven.api_key():
                try:
                    audio, words, dur = eleven.synthesize(pod["say"], pod.get("voice"), log)
                    task.update(custom_audio_file=str(audio), subtitle_enabled=False)
                    log(f"giọng ElevenLabs {dur:.0f} giây; phụ đề karaoke gắn sau khi MoneyPrinterTurbo ghép xong")
                except (eleven.ElevenError, OSError) as exc:
                    log(f"ElevenLabs chưa dùng được ({exc}) → đọc bản podcast bằng giọng {spec.voice}")
            else:
                log("chưa có ELEVENLABS_API_KEY trong video-factory/.env → đọc bản podcast bằng giọng mặc định")
        music = _music(bool(pod))
        log(f"nhạc nền: {music.name}" if music else
            "không chèn nhạc nền (kho nhạc của MoneyPrinterTurbo dính bản quyền; muốn có nhạc thì bỏ nhạc có quyền dùng "
            "vào assets/music/ hoặc thêm trong trình đăng của TikTok/YouTube)")
        local = None
        if image_source(spec) in ("comfyui", "gemini", "commons"):
            if pod:
                log("bản podcast: chưa ghép ảnh vẽ theo lời podcast → dùng clip Pexels")
            else:
                local = LOCAL / f"vf-{workdir.parent.name}"
                shutil.rmtree(local, ignore_errors=True)
                text = spec.narration()
                mp3, ws, dur = synthesize_spec(text, spec)
                attach_punctuation(text, ws)
                clips = sentence_clips(spec, ws, dur, local, log, credits_out=workdir / "credits.txt")
                if clips:
                    words = ws
                    task.update(video_source="local", video_concat_mode="sequential", video_clip_duration=10,
                                video_materials=[{"provider": "local", "url": str(p), "duration": 0} for p in clips],
                                custom_audio_file=str(mp3), subtitle_enabled=False)
                    task.pop("video_terms", None)
                elif image_source(spec) == "commons":   # video về người/sự kiện thật: clip Pexels sẽ sai nội dung
                    shutil.rmtree(local, ignore_errors=True)
                    raise EngineError("chưa lấy đủ ảnh Wikimedia Commons (thường do Wikimedia giới hạn tần suất) — "
                                      "bấm Chạy lại sau vài phút; ảnh đã tải được giữ trong cache")
        # Never let MPT's internal Edge reader override an explicit VieNeu selection.
        # Uploaded podcast audio remains an intentional override.
        if spec.tts_provider == "vieneu" and not task.get("custom_audio_file"):
            text = pod.get("say") or spec.narration()
            mp3, words, dur = synthesize_spec(text, spec)
            attach_punctuation(text, words)
            task.update(custom_audio_file=str(mp3), subtitle_enabled=False)
            log(f"giọng VieNeu {dur:.0f} giây; phụ đề karaoke căn bằng Whisper")
        manifest = workdir / "mpt-manifest.json"
        manifest.write_text(json.dumps([task], ensure_ascii=False), encoding="utf-8")

        log("MoneyPrinterTurbo: " + ("ghép clip ảnh vẽ theo câu với giọng đọc làm sẵn" if task["video_source"] == "local" else
                                     "tải video Pexels") + ", tạo giọng đọc và ghép (thường mất 5–15 phút)")
        try:
            out = run([*venv_python(MPT_DIR / ".venv"), "cli.py", "--batch-file", manifest], cwd=MPT_DIR, log_file=workdir / "log.txt",
                      capture_stdout=True, timeout=3600)
        except EngineError as exc:
            out = exc.stdout   # cli.py thoát mã 1 khi task lỗi nhưng vẫn in kết quả JSON có lý do
            if not out.strip():
                raise
        finally:
            if local:
                shutil.rmtree(local, ignore_errors=True)
        try:
            summary = json.loads(out.strip().splitlines()[-1])
            result = summary["tasks"][0]
        except (IndexError, KeyError, json.JSONDecodeError) as exc:
            raise EngineError(f"không đọc được kết quả cli.py: {exc}")
        if result["status"] != "succeeded":
            raise EngineError(f"bước {result.get('failed_stage')}: {result.get('error')}")
        videos = (result.get("result") or {}).get("videos") or []
        if not videos:
            raise EngineError("cli.py không trả về file video")
        target = workdir / "video.mp4"

        # gắn phụ đề karaoke (bản podcast), trộn nhạc nền người dùng cung cấp, và chuẩn hoá độ to về -14 LUFS
        # (MoneyPrinterTurbo xuất giọng khá nhỏ, ~-22,6 LUFS, nghe yếu hơn hẳn video khác trên TikTok)
        raw = workdir / "video-raw.mp4"
        shutil.copy2(videos[0], raw)
        log_file = workdir / "log.txt"
        cmd = ["ffmpeg", "-v", "error", "-y", "-i", raw.name]
        video = ["-c:v", "copy"]
        if words:
            dur = words[-1]["end"]
            title = esc(pod.get("title") or spec.title)
            (workdir / "captions.ass").write_text(karaoke_ass(
                [dict(w, scene=0) for w in words],
                [(0.0, min(4.0, dur), "Hook", title), (4.0, dur + 1.5, "Kicker", title.upper())]), encoding="utf-8")
            shutil.copytree(FONTS, workdir / "fonts", dirs_exist_ok=True)
            video = ["-vf", "subtitles=captions.ass:fontsdir=fonts", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                     "-pix_fmt", "yuv420p"]
        audio = ["-af", LOUDNORM]
        if music:
            log(f"trộn nhạc nền: {music.name}")
            cmd += ["-stream_loop", "-1", "-i", str(music), "-filter_complex",
                    "[1:a]volume=0.22,aresample=48000[m];[0:a]aresample=48000,asplit=2[v][key];"
                    "[m][key]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck];"
                    f"[v][duck]amix=inputs=2:normalize=0:duration=first,{LOUDNORM}[a]", "-map", "0:v", "-map", "[a]"]
            audio = []
        run([*cmd, *video, *audio, "-ar", "48000", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", target.name],
            cwd=workdir, log_file=log_file)
        return target
