"""AI-auto-generate-video (huytranvan2010): template poster động dựng bằng HyperFrames 0.6.

- Kịch bản chung được chuyển sang script.json (hook / body / outro + template + inputs).
- Repo chỉ biết gọi server OmniVoice (POST /tts {text} → mp3); engine dựng một server nhỏ
  cùng giao thức nhưng dùng Edge TTS, nên không cần cài OmniVoice.
- Repo không gắn phụ đề (để CapCut tự tạo); engine gắn phụ đề karaoke bằng ffmpeg/libass,
  lấy mốc từng từ của Edge TTS và cách repo xếp cảnh (mỗi cảnh cách nhau 0,3 giây).
- Ảnh theo câu (01/10/2026): repo dựng mỗi template 5 giây rồi đứng hình tới hết lời đọc. Engine tạo bản sao tạm
  của template cho từng cảnh (templates/vf-…, xoá sau khi render): kéo dài đúng thời lượng cảnh và lót phía sau nội
  dung một lớp ảnh đổi theo từng câu (bộ ảnh chung với HyperFrames/Remotion, factory/beats.py). Ảnh nhúng base64,
  hiện/zoom bằng CSS animation có độ trễ — runtime HyperFrames tua mọi CSS animation theo thời gian nên khớp từng khung.
  Template gốc không bị sửa.
"""

import base64
import http.server
import json
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

from ..beats import attach as attach_beats
from ..captions import karaoke_ass
from ..config import CHROME, ENGINES_DIR
from ..narration import attach_punctuation, synthesize
from ..spec import Spec
from .base import Engine, EngineError, Log, run, utf8_env

REPO = ENGINES_DIR / "ai-auto-generate-video"
TEMPLATES = REPO / "templates"
FONTS = ENGINES_DIR / "hyperframes-academic" / "fonts"
SCENE_GAP = 0.3  # SCENE_GAP_SEC trong src/render/template-pipeline.ts
OUTRO_HOLD = 3.0  # OUTRO_HOLD_SEC: cảnh cuối giữ thêm 3 giây
ICONS = ["💡", "✅", "📌", "🔒", "🚀"]

# Lớp ảnh nằm dưới mọi thứ của template (z-index -1 trong #root đã tách stacking context). .sheet của bold-poster /
# statement-outro là tấm nền đục phủ kín khung, phải trong suốt thì mới thấy ảnh; blob của liquid-bg-hero mờ bớt.
PHOTO_CSS = """
/* video-factory: ảnh theo câu phía sau nội dung template */
#root { isolation: isolate; }
.sheet { background: transparent !important; }
.blob { opacity: .4 !important; }
.vf-photos { position: absolute; inset: 0; z-index: -1; overflow: hidden; pointer-events: none; }
.vf-ph { position: absolute; inset: 0; background-size: cover; background-position: center; opacity: 0; filter: brightness(.84); }
.vf-scrim { position: absolute; inset: 0; }
@keyframes vfIn { from { opacity: 0; } to { opacity: 1; } }
@keyframes vfZoom { from { transform: scale(1.03); } to { transform: scale(1.10); } }
"""
SCRIM = {
    "dark": "linear-gradient(180deg, rgba(2,8,20,.72) 0%, rgba(2,8,20,.46) 32%, rgba(2,8,20,.56) 66%, rgba(2,8,20,.86) 100%)",
    "light": "linear-gradient(180deg, rgba(245,242,239,.82) 0%, rgba(245,242,239,.9) 50%, rgba(245,242,239,.82) 100%)",
}
LIGHT_TEMPLATES = {"frame-statement-outro"}   # nền kem chữ nâu: phủ sáng, ảnh chỉ thấp thoáng


def cut(text: str, n: int) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= n:
        return text
    head = text[: n - 1].rsplit(" ", 1)[0]
    return (head if len(head) > n // 2 else text[: n - 1]).rstrip(" ,.:;") + "…"


def lines(text: str, width: int, max_lines: int) -> list[str]:
    out, cur = [], ""
    for w in str(text).split():
        if cur and len(cur) + 1 + len(w) > width:
            out.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        out.append(cur)
    return [cut(x, width) for x in out[:max_lines]]


def _diagram_items(spec: Spec, scene: dict) -> list[str]:
    """Tên các thành phần sơ đồ được nhắc tới trong cảnh (để thay sơ đồ bằng danh sách)."""
    elements = {e["id"]: e for e in spec.diagrams.get(scene["diagram"], {}).get("elements", [])}
    names: list[str] = []
    for ev in scene.get("events", []):
        ids = list(ev.get("show", [])) + [a["id"] for a in ([ev["add"]] if isinstance(ev.get("add"), dict) else ev.get("add", []))]
        for i in ids:
            e = elements.get(i, {})
            name = e.get("label_on") or e.get("label") or e.get("text")
            if name and e.get("kind") != "arrow" and name not in names:
                names.append(name)
    return names


def neutralize_branding() -> None:
    """Template của repo gắn cứng thương hiệu tác giả (logo "Senior AI Engineer", nhãn "Bản tin").
    Ẩn các chi tiết đó trong bản clone để video mang thương hiệu của bạn; chạy lại nhiều lần vẫn an toàn."""
    for page in (REPO / "templates").glob("*/compositions/portrait.html"):
        html = page.read_text(encoding="utf-8")
        new = re.sub(r'<div class="brand-bar">.*?</div>', '<div class="brand-bar" style="display:none"></div>', html, flags=re.S)
        new = new.replace("<span>Bản tin</span>", "<span>Bài học</span>").replace("<span>9:16</span>", "<span></span>")
        if new != html:
            page.write_text(new, encoding="utf-8")


def build_script(spec: Spec) -> dict:
    brand = cut(spec.series or "Học nhanh", 24)
    scenes = []
    for i, sc in enumerate(s.model_dump(mode="json") for s in spec.scenes):
        kind, sid = sc["type"], f"s{i + 1:02d}"
        if i == 0 or kind == "title":
            headline = " ".join(tok[0] for tok in sc.get("headline", [])) or spec.title
            item = {"type": "hook", "templateId": "frame-liquid-bg-hero", "inputs": {
                "kicker": cut(sc.get("tag") or brand, 24), "headline": cut(headline, 60),
                "subheadline": cut(sc.get("sub") or spec.title, 120),
                "cta": cut(f"Tập {spec.ep}/{spec.total}" if spec.ep and spec.total else "Xem hết nhé", 24), "brand": brand}}
        elif kind == "next" or i == len(spec.scenes) - 1:
            # nhãn lấy từ kịch bản ("GHI NHỚ", "TIẾP THEO"); series ôn thi không ghi nhãn thì là "Tập sau"
            prefix = (sc.get("label") or ("Tập sau" if spec.ep else "")).strip().capitalize()
            cta = (f"{prefix}: {sc.get('title', '')}" if prefix else sc.get("title", "")) if kind == "next" else "Theo dõi để xem tiếp"
            item = {"type": "outro", "templateId": "frame-statement-outro", "inputs": {
                "cta": cut(cta, 60), "channel": brand, "source": cut(sc.get("sub") or spec.title, 40)}}
        elif kind == "tip":
            item = {"type": "body", "templateId": "frame-bold-poster", "inputs": {
                "kicker": cut(sc.get("label") or "MẸO THI", 24), "date": brand, "figure": "?",
                "headline": lines(sc["answer"], 14, 3) or ["ĐÁP ÁN"], "standfirst": cut(sc["question"], 160),
                "footer_left": brand, "footer_right": cut((sc.get("a_label") or "Đáp án").capitalize(), 24)}}
        elif kind == "stat":
            st = sc["stats"]
            item = {"type": "body", "templateId": "frame-vignelli", "inputs": {
                "kicker": cut(sc.get("heading") or sc.get("kicker") or "", 30), "number": cut(st[0]["value"], 6),
                "label": cut(st[0].get("label", ""), 40), "note": cut(" · ".join(f"{x['value']} {x.get('label', '')}" for x in st[1:]), 120),
                "brand": brand}}
        elif kind == "compare" and len(sc["left"].get("title", "")) <= 8 and len(sc["right"].get("title", "")) <= 8:
            side = lambda d, a, b: {"label": d["title"], "from": a, "to": b, "bullets": [cut(p, 40) for p in d.get("points", [])][:4]}
            item = {"type": "body", "templateId": "frame-aicoding-comparison", "inputs": {
                "badge": cut(sc.get("kicker") or "So sánh", 16), "vs": "vs",
                "left": side(sc["left"], "#7c5cff", "#22d3ee"), "right": side(sc["right"], "#ffb020", "#ff7a3d")}}
        else:
            # (tên ý, mô tả nhỏ): "S3 Standard: Dữ liệu dùng liên tục" → tên + mô tả để template khỏi cắt cụt
            if kind == "bullets":
                rows = [tuple(x.strip() for x in it["text"].split(":", 1)) if ":" in it["text"] else (it["text"], "")
                        for it in sc["items"]]
            elif kind == "compare":
                rows = [(sc[k]["title"], ", ".join(sc[k].get("points", []))) for k in ("left", "right")]
            elif kind == "flow":   # sơ đồ luồng → danh sách các nút theo thứ tự xuất hiện
                labels = {n["id"]: n.get("label", "") for n in sc["nodes"]}
                order = [i for st in sc.get("steps", []) for i in st.get("show", []) if i in labels]
                rows = [(labels[i], "") for i in dict.fromkeys(order + list(labels))]
            else:  # diagram → danh sách thành phần được nhắc tới
                rows = [(n, "") for n in _diagram_items(spec, sc)]
            rows = rows[:5]
            if len(rows) >= 2:
                item = {"type": "body", "templateId": "frame-aicoding-list", "inputs": {
                    "title": cut(sc.get("heading", ""), 40), "subtitle": cut(sc.get("kicker", ""), 60),
                    "accent_from": "#7c5cff", "accent_to": "#22d3ee",
                    "items": [{"icon": ICONS[j % len(ICONS)], "title": cut(t, 24), "desc": cut(d, 40), "tag": f"{j + 1:02d}", "level": "info"}
                              for j, (t, d) in enumerate(rows)]}}
            else:
                item = {"type": "body", "templateId": "frame-build-minimal", "inputs": {
                    "eyebrow": cut(sc.get("kicker") or brand, 20), "hero": cut((rows[0][0] if rows else sc.get("heading", "")).split()[0], 10),
                    "desc": cut(sc.get("heading", ""), 90), "side_left": brand, "side_right": cut(sc.get("step", ""), 20)}}
        scenes.append({"id": sid, "voiceText": sc["say"], **item})
    return {
        "version": "1.0", "renderer": "hyperframes", "aspect": "9:16",
        "metadata": {"title": spec.title, "source": {"url": "", "domain": "", "image": None}, "channel": brand},
        "voice": {"provider": "omnivoice", "speed": 1.0},
        "scenes": scenes,
    }


class _TTSServer:
    """Server giả lập OmniVoice: POST /tts {"text": ...} → mp3 do Edge TTS đọc."""

    def __init__(self, voice: str, log: Log):
        voice_ = voice

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                try:
                    body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                    mp3, _, _ = synthesize(body["text"], voice_)
                    data = mp3.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "audio/mpeg")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except Exception as exc:  # repo sẽ tự thử lại khi gặp 5xx
                    log(f"TTS lỗi: {exc}")
                    self.send_error(500, str(exc)[:200])

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def build_ass(script: dict, voice: str) -> str:
    """Phụ đề karaoke theo cách repo xếp cảnh (mỗi cảnh cách nhau SCENE_GAP)."""
    words, cursor = [], 0.0
    for i, sc in enumerate(script["scenes"]):
        mp3, ws, dur = synthesize(sc["voiceText"], voice)   # trúng cache từ lúc repo gọi TTS
        attach_punctuation(sc["voiceText"], ws)
        words += [dict(w, start=w["start"] + cursor, end=w["end"] + cursor, scene=i) for w in ws]
        cursor += dur + SCENE_GAP
    return karaoke_ass(words)


def _with_photos(html: str, layer: list[tuple[float, float, Path]], seconds: float, light: bool) -> str:
    """Kéo dài composition thành `seconds` giây và lót lớp ảnh [(t0, t1, ảnh)] (giây tính từ đầu cảnh) sau nội dung."""
    m = re.search(r'<div\b[^>]*\bid="root"[^>]*>', html, re.S)
    if not m or "</style>" not in html:
        raise EngineError("template không có #root hoặc <style> — không chèn được ảnh")
    tag = re.sub(r'data-duration="[^"]*"', f'data-duration="{seconds:.3f}"', m.group(0), count=1)
    items = []
    for t0, t1, img in layer:
        mime = "image/png" if img.suffix.lower() == ".png" else "image/jpeg"
        uri = f"data:{mime};base64," + base64.b64encode(img.read_bytes()).decode()
        fade = 0.45 if t0 > 0.01 else 0.01      # ảnh đầu cảnh hiện ngay cùng lúc chuyển cảnh
        items.append(f'<div class="vf-ph" style="background-image:url({uri});animation:vfIn {fade}s ease-out {t0:.3f}s both,'
                     f'vfZoom {max(1.0, t1 - t0 + 0.45):.3f}s linear {t0:.3f}s both"></div>')
    scrim = SCRIM["light" if light else "dark"]
    layer_html = f'<div class="vf-photos">{"".join(items)}<div class="vf-scrim" style="background:{scrim}"></div></div>'
    html = html[:m.start()] + tag + layer_html + html[m.end():]
    return html.replace("</style>", PHOTO_CSS + "</style>", 1)


def photo_templates(spec: Spec, script: dict, dest: Path, log: Log) -> list[Path]:
    """Tạo template tạm có ảnh theo câu cho từng cảnh, đổi templateId trong script; trả về các thư mục cần xoá."""
    # Bản tạm sót lại của lần render bị ngắt giữa chừng: tuổi đọc từ tên (vf-<giờ tạo>-…), không dùng mtime — copytree
    # chép cả mtime của template gốc nên bản vừa tạo trông như cũ, từng xoá nhầm template của job đang chạy song song.
    for old in TEMPLATES.glob("vf-*"):
        made_at = old.name.split("-")[1]
        if not made_at.isdigit() or time.time() - int(made_at) > 6 * 3600:
            shutil.rmtree(old, ignore_errors=True)
    words, scenes, cursor = [], [], 0.0
    last = len(script["scenes"]) - 1
    for i, sc in enumerate(script["scenes"]):
        _, ws, dur = synthesize(sc["voiceText"], spec.voice)
        attach_punctuation(sc["voiceText"], ws)
        words += [dict(w, start=w["start"] + cursor, end=w["end"] + cursor) for w in ws]
        seconds = dur + (SCENE_GAP if i < last else OUTRO_HOLD)
        scenes.append({"type": spec.scenes[i].type, "start": cursor, "end": cursor + seconds, "seconds": seconds})
        cursor += dur + SCENE_GAP
    data = {"scenes": scenes, "words": words}
    if not attach_beats(spec, data, dest, "", log):
        return []
    key, made = f"{int(time.time())}-{uuid.uuid4().hex[:6]}", []
    for i, sc in enumerate(script["scenes"]):
        mine = [b for b in data["beats"] if b["scene"] == i]
        if not mine:
            continue
        s = scenes[i]
        layer = [(max(0.0, b["t0"] - s["start"]), min(s["seconds"], b["t1"] - s["start"]), dest / b["src"]) for b in mine]
        new_id = f"vf-{key}-{sc['id']}"
        folder = TEMPLATES / new_id
        shutil.copytree(TEMPLATES / sc["templateId"], folder)
        made.append(folder)
        entry = folder / "compositions" / "portrait.html"
        entry = entry if entry.exists() else folder / "index.html"
        entry.write_text(_with_photos(entry.read_text(encoding="utf-8"), layer, s["seconds"],
                                      sc["templateId"] in LIGHT_TEMPLATES), encoding="utf-8")
        sc["templateId"] = new_id
    log(f"ảnh theo câu: {sum(1 for b in data['beats'])} ảnh trên {len(made)} cảnh")
    return made


class AIAutoGenerateVideo(Engine):
    key = "aiauto"
    label = "AI-auto-generate-video"
    style = "Template poster động trên ảnh đổi theo câu (HyperFrames 0.6), phụ đề karaoke"

    def check(self):
        if not (REPO / "node_modules").exists():
            return False, "chưa cài: chạy cai-dat.cmd (clone repo vào engines/ai-auto-generate-video + npm ci)"
        return True, ""

    def render(self, spec: Spec, workdir: Path, log: Log) -> Path:
        neutralize_branding()
        script = build_script(spec)
        log(f"chuyển kịch bản sang {len(script['scenes'])} cảnh template: " + ", ".join(s["templateId"] for s in script["scenes"]))

        # Tạo sẵn giọng đọc từng cảnh (có thử lại) để server giả lập trả ngay từ cache: repo ngắt kết nối
        # ("socket hang up") nếu Edge TTS phản hồi chậm, mà Edge đôi khi chậm vài phút.
        for i, sc in enumerate(script["scenes"], 1):
            log(f"tạo giọng đọc cảnh {i}/{len(script['scenes'])}")
            synthesize(sc["voiceText"], spec.voice)

        temp = photo_templates(spec, script, workdir / "photos", log)
        script_path = workdir / "script.json"
        script_path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
        tts = _TTSServer(spec.voice, log)
        try:
            log("chạy pipeline của repo (render từng template, ghép) — lần đầu npx tải hyperframes 0.6.94")
            env = utf8_env(TTS_PROVIDER="omnivoice", OMNIVOICE_ENDPOINT=tts.url, TTS_CONCURRENCY="1",
                           HYPERFRAMES_BROWSER_PATH=str(CHROME), HYPERFRAMES_NO_TELEMETRY="1", DO_NOT_TRACK="1",
                           HYPERFRAMES_NO_UPDATE_CHECK="1", NPM_CONFIG_UPDATE_NOTIFIER="false")
            run(["npm.cmd", "run", "pipeline", "--", script_path], cwd=REPO, log_file=workdir / "log.txt", env=env, timeout=3600)
        finally:
            tts.close()
            for folder in temp:
                shutil.rmtree(folder, ignore_errors=True)
            shutil.rmtree(workdir / "photos", ignore_errors=True)

        raw = workdir / "video.mp4"
        if not raw.exists():
            raise RuntimeError("pipeline chạy xong nhưng không thấy video.mp4")
        log("gắn phụ đề karaoke")
        (workdir / "captions.ass").write_text(build_ass(script, spec.voice), encoding="utf-8")
        shutil.copytree(FONTS, workdir / "fonts", dirs_exist_ok=True)
        run(["ffmpeg", "-v", "error", "-y", "-i", "video.mp4", "-vf", "subtitles=captions.ass:fontsdir=fonts",
             "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "copy",
             "-movflags", "+faststart", "video-captioned.mp4"], cwd=workdir, log_file=workdir / "log.txt")
        (workdir / "video-raw.mp4").unlink(missing_ok=True)
        raw.rename(workdir / "video-raw.mp4")
        (workdir / "video-captioned.mp4").rename(raw)
        return raw
