"""HyperFrames: template học thuật nền sáng (sơ đồ dựng dần, phụ đề karaoke) render bằng HyperFrames.

Mỗi job dựng một composition riêng: index.html (template + dữ liệu dòng thời gian), narration.wav, fonts/.
template.html đăng ký window.__timelines.main bọc quanh renderAt(t) nên HyperFrames tua được từng khung.
"""

import json
import shutil
from pathlib import Path

from ..beats import attach as attach_beats
from ..config import CHROME, ENGINES_DIR
from ..narration import build_audio, build_timeline
from ..spec import Spec
from .base import Engine, Log, run, utf8_env

PROJECT = ENGINES_DIR / "hyperframes-academic"
CLI = PROJECT / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"
TEMPLATE = PROJECT / "template.html"

QUIET_ENV = {
    "HYPERFRAMES_BROWSER_PATH": str(CHROME),   # Chrome cài sẵn, tránh bản headless-shell hay crash trên Windows
    "HYPERFRAMES_NO_TELEMETRY": "1",
    "DO_NOT_TRACK": "1",
    "HYPERFRAMES_NO_UPDATE_CHECK": "1",
    "HYPERFRAMES_NO_FEEDBACK": "1",
    "HYPERFRAMES_NO_AUTO_INSTALL": "1",
}


def build_composition(spec: Spec, comp: Path, log: Log, audio: bool = True) -> dict:
    """Dựng thư mục composition (index.html + fonts + narration.wav); trả về dữ liệu dòng thời gian."""
    data, parts = build_timeline(spec, log)
    comp.mkdir(parents=True, exist_ok=True)
    attach_beats(spec, data, comp / "beats", "beats/", log)   # ảnh nền theo từng câu kể
    if audio:
        build_audio(parts, comp / "narration.wav", data, spec.title)
    html = (TEMPLATE.read_text(encoding="utf-8")
            .replace("__DURATION__", f"{data['duration']:.3f}")
            .replace("__DATA_JSON__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/")))
    (comp / "index.html").write_text(html, encoding="utf-8")
    shutil.copytree(PROJECT / "fonts", comp / "fonts", dirs_exist_ok=True)
    return data


class HyperFrames(Engine):
    key = "hyperframes"
    label = "HyperFrames"
    style = "Motion graphics học thuật trên ảnh đổi theo câu, sơ đồ dựng dần, phụ đề karaoke"

    def check(self):
        if not CLI.exists():
            return False, "chưa cài: chạy python3 cai-dat.py (npm ci trong engines/hyperframes-academic)"
        if not TEMPLATE.exists():
            return False, "thiếu template.html (chạy build_template.py)"
        return True, ""

    def render(self, spec: Spec, workdir: Path, log: Log) -> Path:
        log(f"tạo giọng đọc {spec.tts_provider} và dòng thời gian từng từ")
        comp = workdir / "comp"
        data = build_composition(spec, comp, log)

        log(f"HyperFrames render {data['duration']:.0f}s video")
        out = workdir / "video.mp4"
        run(["node", CLI, "render", comp, "--output", out, "--fps", "30", "--workers", "4", "--quiet"],
            cwd=PROJECT, log_file=workdir / "log.txt", env=utf8_env(**QUIET_ENV), timeout=1800)
        return out
