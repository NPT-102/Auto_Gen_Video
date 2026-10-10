"""Pixelle-Video: mỗi câu một khung (template của Pixelle), giọng Edge TTS hoặc VieNeu làm sẵn.

Từ 01/10/2026 mỗi câu kèm một ảnh (bộ ảnh theo câu dùng chung với HyperFrames/Remotion, factory/beats.py), dựng bằng
template image_modern. Pipeline chuẩn của Pixelle chạy trong venv của nó qua pixelle_driver.py: chế độ "fixed" + tiêu
đề có sẵn + ảnh gắn sẵn cho từng khung ⇒ Pixelle không gọi LLM hay model vẽ ảnh nào, cũng không cần server API (bản
trước gọi HTTP API ở cổng 8612). Không có ảnh (thiếu key Pexels, "images": false) thì dùng thẻ chữ static_factory.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

from ..beats import attach as attach_beats
from ..config import ENGINES_DIR
from ..narration import build_timeline, synthesize_spec
from ..pyrun import python_path, venv_python
from ..spec import Spec
from .base import Engine, EngineError, Log, run, utf8_env

REPO = ENGINES_DIR / "pixelle-video"
PYTHON = python_path(REPO / ".venv")
DRIVER = Path(__file__).with_name("pixelle_driver.py")
TEMPLATE = "1080x1920/static_factory.html"   # bản sao static_default, nhãn góc lấy từ biến {{tagline}}
PHOTO_TEMPLATE = "1080x1920/image_modern.html"
BACKGROUND = ENGINES_DIR / "pixelle-assets" / "bg.jpg"


def _background() -> str:
    if not BACKGROUND.exists():
        BACKGROUND.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "gradients=s=1080x1920:c0=0x1d4ed8:c1=0x0f172a:c2=0x7c3aed:x0=0:y0=0:x1=1080:y1=1920:nb_colors=3",
                        "-frames:v", "1", str(BACKGROUND)], check=True)
    return BACKGROUND.as_uri()


def _ensure_template() -> None:
    """Pixelle cho phép thêm template riêng vào templates/; tạo bản không có nhãn "Text-Only Template" gắn cứng."""
    ours = REPO / "templates" / TEMPLATE
    src = REPO / "templates" / "1080x1920" / "static_default.html"
    if not ours.exists() or ours.stat().st_mtime < src.stat().st_mtime:
        html = src.read_text(encoding="utf-8").replace(
            '<div class="logo-subtitle">Text-Only Template</div>', '<div class="logo-subtitle">{{tagline=Lưu lại để ôn tập}}</div>')
        ours.write_text(html, encoding="utf-8")


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?…])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", text.lower()).split())


def sentence_photos(spec: Spec, sents: list[tuple[int, str]], dest: Path, log: Log) -> list[str | None]:
    """Ảnh cho từng câu (scene, câu): khớp câu với beat chứa nó trong bộ ảnh theo câu; câu thuộc cảnh sơ đồ (không
    có beat) dùng lại ảnh liền trước."""
    data, _ = build_timeline(spec, log)
    if not attach_beats(spec, data, dest, "", log):
        return [None] * len(sents)
    beats, out, seen = data["beats"], [], {}
    for scene, text in sents:
        k = seen[scene] = seen.get(scene, -1) + 1
        mine = [b for b in beats if b["scene"] == scene]
        hit = next((b for b in mine if _norm(text) in _norm(b["text"])), None) or (mine[min(k, len(mine) - 1)] if mine else None)
        out.append(str(dest / hit["src"]) if hit else (out[-1] if out else None))
    first = next((x for x in out if x), None)
    return [x or first for x in out]


class PixelleVideo(Engine):
    key = "pixelle"
    label = "Pixelle-Video"
    style = "Mỗi câu một khung: ảnh theo câu + chữ trên nền tím"

    def check(self):
        if not PYTHON.exists():
            return False, "chưa cài: chạy python3 cai-dat.py (clone Pixelle-Video vào engines/pixelle-video + uv sync)"
        return True, ""

    def render(self, spec: Spec, workdir: Path, log: Log) -> Path:
        sents = [(i, s) for i, sc in enumerate(spec.scenes) for s in sentences(sc.say)]
        photos = workdir / "photos"
        images = sentence_photos(spec, sents, photos, log)
        photo = any(images)
        if not photo:
            _ensure_template()
        config = REPO / "config.yaml"
        if not config.exists():
            shutil.copy2(REPO / "config.example.yaml", config)
        brand = spec.series or "Học nhanh"
        job = {
            "text": "\n\n".join(s for _, s in sents),   # chế độ fixed: mỗi đoạn một khung
            "title": spec.title,
            "voice_id": spec.voice,
            "frame_template": PHOTO_TEMPLATE if photo else TEMPLATE,
            "images": images if photo else [],
            "template_params": {"author": brand, "brand": brand, "describe": spec.title, "accent_color": "#7c3aed",
                                "background": _background(),
                                "tagline": f"Tập {spec.ep}/{spec.total}" if spec.ep and spec.total else "Lưu lại để ôn tập"},
        }
        if spec.tts_provider == "vieneu":
            log(f"tạo giọng VieNeu cho {len(sents)} khung")
            job["audio"] = []
            for _, text in sents:
                audio, _, duration = synthesize_spec(text, spec)
                job["audio"].append({"path": str(audio), "duration": duration})
        job_file = workdir / "pixelle-job.json"
        job_file.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        log(f"Pixelle dựng {len(sents)} khung " + ("có ảnh theo câu" if photo else "thẻ chữ (không có ảnh)"))
        try:
            out = run([*venv_python(REPO / ".venv"), DRIVER, job_file], cwd=REPO, log_file=workdir / "log.txt",
                      env=utf8_env(PYTHONPATH=str(REPO)), timeout=3600, capture_stdout=True)
        finally:
            shutil.rmtree(photos, ignore_errors=True)
        try:
            video = Path(json.loads(out.strip().splitlines()[-1])["video"])
        except (IndexError, KeyError, ValueError) as exc:
            raise EngineError(f"Pixelle không trả về đường dẫn video: {out[-300:]}") from exc
        video = video if video.is_absolute() else REPO / video
        target = workdir / "video.mp4"
        shutil.copy2(video, target)
        return target
