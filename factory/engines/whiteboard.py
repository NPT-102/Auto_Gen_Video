"""Whiteboard video: render each narrated beat through Whiteboard Lab, then
use a separate Remotion project for captions, transitions and final audio."""

import json
import re
import shutil
import sys
import uuid
from pathlib import Path

from ..beats import attach as attach_beats
from ..config import CHROME, ENGINES_DIR, ROOT, WHITEBOARD_LAB_DIR
from ..narration import build_audio, build_timeline
from ..spec import Spec
from ..whiteboard_planner import plan_from_spec
from .base import Engine, Log, run, utf8_env

PROJECT = ENGINES_DIR / "remotion-whiteboard"
CLI = PROJECT / "node_modules" / "@remotion" / "cli" / "remotion-cli.js"
FPS = 30

def scene_beats(data: dict, spec: Spec) -> list[dict]:
    """One coherent illustration for each narration scene.

    A whiteboard scene is a composition whose objects are revealed by the Lab;
    it is not a collage of unrelated stock photos in fixed grid slots.
    """
    return [
        {
            "scene": index,
            "t0": float(scene["start"]),
            "t1": float(scene["end"]),
            # build_timeline intentionally removes `say` from its render data.
            # Read the original narration from Spec so every scene still gets
            # an illustration request.
            "text": str(spec.scenes[index].say),
        }
        for index, scene in enumerate(data["scenes"])
        if str(spec.scenes[index].say).strip()
    ]


def scene_direction(scene: dict, index: int) -> dict:
    """Choose a modest camera and scene hand-off from the script structure.

    This stays deterministic so the outer pipeline can replace it with an LLM
    storyboard later without changing the Remotion contract.
    """
    kind = str(scene.get("type", ""))
    # The reference style is a readable page that grows over time.  Motion is
    # opt-in; a camera that constantly hunts individual icons makes a board
    # feel like a slideshow instead of a drawing.
    return {"camera": "static", "transition": "clear", "accent": "settle"}


def lab_python() -> Path | None:
    # Whiteboard Lab keeps its isolated interpreter in .venv/, like Factory.
    # Keep the two legacy locations for an existing checkout created differently.
    names = (".venv/Scripts/python.exe", ".venv/bin/python", "Scripts/python.exe", "bin/python")
    return next((WHITEBOARD_LAB_DIR / name for name in names if (WHITEBOARD_LAB_DIR / name).exists()), None)


def split_scene_objects(python: Path, source: Path, output_dir: Path, workdir: Path) -> dict:
    """Ask Whiteboard Lab for a small, spatially coherent layer plan."""
    raw = run([python, "-m", "lab.module", "--image", source, "--split-objects", output_dir],
              cwd=WHITEBOARD_LAB_DIR, log_file=workdir / "log.txt", env=utf8_env(),
              timeout=300, capture_stdout=True)
    try:
        return json.loads(raw.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError("Whiteboard Lab did not return a valid object-layer manifest") from exc


def layer_durations(seconds: float, layers: list[dict]) -> list[float] | None:
    """Give every object a visible drawing window, or choose one whole scene."""
    minimum = 0.75
    if not layers or len(layers) * minimum > seconds:
        return None
    remaining = max(0.0, seconds - len(layers) * minimum)
    weights = [max(0.01, float(layer.get("weight", 1))) for layer in layers]
    total = sum(weights)
    return [minimum + remaining * weight / total for weight in weights]


def layer_schedule(seconds: float, layers: list[dict]) -> list[tuple[float, float]] | None:
    """Return each object's start offset and drawing duration.

    A plan can give every object an `at` value.  Values from 0 to 1 mean a
    fraction of this narration scene; larger values mean seconds.  If the
    requested timing leaves too little time to visibly draw an object, fall
    back to the reliable sequential schedule instead of producing a frantic
    flash of drawings.
    """
    durations = layer_durations(seconds, layers)
    if durations is None:
        return None
    requested: list[float] = []
    for layer in layers:
        value = layer.get("at")
        if value is None:
            return list(zip([sum(durations[:i]) for i in range(len(durations))], durations))
        try:
            value = float(value)
        except (TypeError, ValueError):
            return list(zip([sum(durations[:i]) for i in range(len(durations))], durations))
        requested.append(seconds * value if 0 <= value <= 1 else value)
    if requested != sorted(requested):
        return list(zip([sum(durations[:i]) for i in range(len(durations))], durations))
    minimum = 0.65
    windows = []
    for index, start in enumerate(requested):
        start = max(0.0, start)
        end = requested[index + 1] if index + 1 < len(requested) else seconds
        if end - start < minimum:
            return list(zip([sum(durations[:i]) for i in range(len(durations))], durations))
        windows.append((start, end - start))
    return windows


def assemble_pages(beats: list[dict]) -> list[dict]:
    """Combine consecutive beats that belong to one whiteboard page.

    A scene is a narration unit; a page is a visual unit.  Keeping those two
    units separate lets one drawing keep growing while several narration
    sentences are spoken.
    """
    pages: list[dict] = []
    for index, beat in enumerate(beats, 1):
        key = beat.get("page", index)
        if not pages or pages[-1]["key"] != key:
            pages.append({"key": key, "t0": float(beat["t0"]), "t1": float(beat["t1"]),
                          "layers": [], "motion": beat.get("motion")})
        page = pages[-1]
        page["t1"] = float(beat["t1"])
        page["layers"].extend(beat.get("layers") or [])
    for page in pages:
        for layer in page["layers"]:
            layer["hold_t1"] = round(page["t1"], 3)
        page.pop("key", None)
    return pages


def attach_local_assets(spec: Spec, data: dict, dest: Path, prefix: str) -> None:
    """Use prepared image files instead of asking an image provider.

    This is useful for a reviewed storyboard and for visual regression demos.
    Paths are always relative to Factory's root, so a content JSON cannot read
    arbitrary files elsewhere on the machine.
    """
    raw_assets = list((spec.model_extra or {}).get("whiteboard_assets") or [])
    beats = scene_beats(data, spec)
    if len(raw_assets) != len(beats):
        raise ValueError(f"whiteboard_assets needs {len(beats)} image paths, got {len(raw_assets)}")
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for index, (beat, raw_path) in enumerate(zip(beats, raw_assets), 1):
        source = (ROOT / str(raw_path)).resolve()
        if ROOT.resolve() not in source.parents or not source.is_file():
            raise ValueError(f"whiteboard asset not found: {raw_path}")
        if source.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError(f"whiteboard asset must be PNG, JPG, JPEG or WEBP: {raw_path}")
        name = f"b{index:02d}{source.suffix.lower()}"
        shutil.copy2(source, dest / name)
        out.append({**beat, "src": f"{prefix}{name}", "provider": "prepared"})
    data["beats"] = out


def attach_planned_assets(python: Path, spec: Spec, data: dict, dest: Path, workdir: Path,
                          scenes: list[dict] | None = None) -> None:
    """Turn a declarative whiteboard plan into independent drawable layers."""
    scenes = list(scenes if scenes is not None else (spec.model_extra or {}).get("whiteboard_plan") or [])
    beats = scene_beats(data, spec)
    if len(scenes) != len(beats):
        raise ValueError(f"whiteboard_plan needs {len(beats)} scene plans, got {len(scenes)}")
    plan_file = dest / "whiteboard-plan.json"
    plan_dir = dest / "planned-assets"
    dest.mkdir(parents=True, exist_ok=True)
    workdir.mkdir(parents=True, exist_ok=True)
    plan_file.write_text(json.dumps({"scenes": scenes}, ensure_ascii=False), encoding="utf-8")
    raw = run([python, ROOT / "tools" / "render_whiteboard_plan.py", "--plan", plan_file, "--out-dir", plan_dir],
              cwd=ROOT, log_file=workdir / "log.txt", env=utf8_env(), timeout=300, capture_stdout=True)
    try:
        manifest = json.loads(raw.strip().splitlines()[-1])
        rendered_scenes = list(manifest["scenes"])
    except (IndexError, KeyError, json.JSONDecodeError) as exc:
        raise RuntimeError("whiteboard plan renderer did not return a valid manifest") from exc
    if len(rendered_scenes) != len(beats):
        raise RuntimeError("whiteboard plan renderer returned the wrong number of scenes")
    data["beats"] = [
        {
            **beat,
            "provider": "planned",
            # Consecutive narration scenes can share a page.  Their drawings
            # remain visible until the next page begins.
            "page": rendered.get("page", index),
            "_planned_layers": [
                {**layer, "path": str(plan_dir / layer["file"])}
                for layer in rendered["layers"]
            ],
            "_planned_composite": str(plan_dir / rendered["composite"]),
        }
        for index, (beat, rendered) in enumerate(zip(beats, rendered_scenes), 1)
    ]


class Whiteboard(Engine):
    key = "whiteboard"
    label = "Whiteboard"
    style = "Bàn tay vẽ ảnh minh họa theo từng câu, Remotion ghép phụ đề và giọng đọc"

    def check(self):
        if not CLI.exists():
            return False, "chưa cài: chạy npm ci trong engines/remotion-whiteboard"
        python = lab_python()
        if python is None or not (WHITEBOARD_LAB_DIR / "lab" / "module.py").exists():
            return False, f"không tìm thấy Whiteboard Lab ở {WHITEBOARD_LAB_DIR}"
        return True, ""

    def render(self, spec: Spec, workdir: Path, log: Log) -> Path:
        log(f"tạo giọng đọc {spec.tts_provider} và dòng thời gian từng từ")
        data, parts = build_timeline(spec, log)
        job = uuid.uuid4().hex[:12]
        beat_dir = PROJECT / "public" / "jobs" / job
        # One coherent illustration per narration scene.  The Lab reveals the
        # objects inside it; never build a fixed grid of unrelated photos.
        if spec.model_extra is not None:
            spec.model_extra["image_style"] = "whiteboard"
        python = lab_python()
        if python is None:
            raise RuntimeError(f"Whiteboard Lab Python not found at {WHITEBOARD_LAB_DIR}")
        layout = str((spec.model_extra or {}).get("whiteboard_layout", "plan"))
        if layout not in {"plan", "image"}:
            raise ValueError("whiteboard_layout must be plan or image")
        if (spec.model_extra or {}).get("whiteboard_plan"):
            attach_planned_assets(python, spec, data, beat_dir, workdir)
            log(f"whiteboard storyboard: {len(data['beats'])} scene(s)")
        elif layout == "plan":
            attach_planned_assets(python, spec, data, beat_dir, workdir, plan_from_spec(spec))
            log(f"whiteboard storyboard auto-plan: {len(data['beats'])} scene(s)")
        elif (spec.model_extra or {}).get("whiteboard_assets"):
            attach_local_assets(spec, data, beat_dir, f"jobs/{job}/")
            log(f"dÃ¹ng {len(data['beats'])} áº£nh whiteboard Ä‘Ã£ chuáº©n bá»‹")
        else:
            attach_beats(spec, data, beat_dir, f"jobs/{job}/", log, credits_out=workdir / "credits.txt",
                         beats=scene_beats(data, spec))
        for beat in data.get("beats", []):
            beat["motion"] = scene_direction(data["scenes"][int(beat["scene"])], int(beat["scene"]))
        # Clean paper is the default.  A caller can deliberately turn the
        # overlay back on for a social-media variant.
        data["whiteboard"] = {
            "captions": bool((spec.model_extra or {}).get("whiteboard_captions", False)),
            "header": bool((spec.model_extra or {}).get("whiteboard_header", False)),
        }
        mode = str((spec.model_extra or {}).get("whiteboard_mode", "auto"))
        if mode not in {"auto", "outline_color", "direct_color"}:
            raise ValueError("whiteboard_mode phải là auto, outline_color hoặc direct_color")
        python = lab_python()
        if python is None:
            raise RuntimeError(f"Không tìm thấy Python của Whiteboard Lab ở {WHITEBOARD_LAB_DIR}")
        clips = beat_dir / "whiteboard"
        try:
            for index, beat in enumerate(data.get("beats", []), 1):
                planned_layers = beat.pop("_planned_layers", None)
                planned_composite = beat.pop("_planned_composite", None)
                source = PROJECT / "public" / beat["src"] if not planned_layers else None
                seconds = max(0.1, float(beat["t1"]) - float(beat["t0"]))
                objects_dir = beat_dir / "objects" / f"scene-{index:02d}"
                if planned_layers:
                    layers = [
                        {"file": None, "path": item["path"], "weight": item.get("weight", 1.0),
                         "bbox": item["bbox"], "at": item.get("at")}
                        for item in planned_layers
                    ]
                    fallback = False
                else:
                    manifest = split_scene_objects(python, source, objects_dir, workdir)
                    layers = list(manifest.get("layers") or [])
                    fallback = bool(manifest.get("fallback"))
                schedule = layer_schedule(seconds, layers)
                # A short narration line cannot show six separate drawings
                # clearly. Keep the original whole composition in that case,
                # rather than silently dropping smaller objects.
                if schedule is None:
                    layers = [{"file": None, "path": planned_composite, "weight": 1.0,
                               "bbox": {"x": 0, "y": 0, "w": 1, "h": 1}}]
                    schedule = [(0.0, seconds)]
                    fallback = True

                # Primitive doodles are deliberately line art.  Auto mode
                # misclassifies their thin black strokes as a colour fill.
                render_mode = "outline_color" if planned_layers and mode == "auto" else mode
                log(f"whiteboard part {index}/{len(data['beats'])}: {len(layers)} layer(s), {seconds:.1f}s ({render_mode})")
                rendered_layers = []
                for layer_index, (layer, (offset, draw_seconds)) in enumerate(zip(layers, schedule), 1):
                    layer_source = (Path(layer["path"]) if layer.get("path") else
                                    source if layer["file"] is None else objects_dir / layer["file"])
                    target = clips / f"wb{index:02d}-{layer_index:02d}.mp4"
                    run([python, "-m", "lab.module", "--image", layer_source, "--output", target,
                         "--duration", f"{draw_seconds:.3f}", "--mode", render_mode],
                        cwd=WHITEBOARD_LAB_DIR, log_file=workdir / "log.txt", env=utf8_env(), timeout=1800)
                    # Do not freeze a frame from the drawing MP4 after it
                    # ends. Remotion's nested timeline can seek that clip
                    # back into its drawing phase. Keep a plain final still
                    # beside it instead; it also removes the idle hand.
                    still = target.with_name(f"{target.stem}-still{layer_source.suffix.lower()}")
                    shutil.copy2(layer_source, still)
                    draw_start = float(beat["t0"]) + offset
                    draw_end = min(float(beat["t1"]), draw_start + draw_seconds)
                    rendered_layers.append({
                        "t0": round(draw_start, 3), "draw_t1": round(draw_end, 3),
                        "hold_t1": round(float(beat["t1"]), 3),
                        "clip": f"jobs/{job}/whiteboard/{target.name}",
                        "still": f"jobs/{job}/whiteboard/{still.name}",
                        "bbox": layer["bbox"],
                        # White areas in split PNGs are transparent paper in
                        # the compositor. A whole scene retains normal colour.
                        "blend": "normal" if fallback else "multiply",
                    })
                beat["layers"] = rendered_layers
                beat.pop("clip", None)

            data["whiteboard_pages"] = assemble_pages(data.get("beats", []))
            wav = workdir / "narration.wav"
            build_audio(parts, wav, data, spec.title)
            props = workdir / "props.json"
            props.write_text(json.dumps({"data": data, "audio": ""}, ensure_ascii=False), encoding="utf-8")
            out, frames = workdir / "video.mp4", beat_dir / "frames"
            shutil.rmtree(frames, ignore_errors=True)
            log(f"Remotion ghép {len(data.get('beats', []))} cảnh whiteboard, {data['duration']:.0f}s")
            run(["node", CLI, "render", "src/index.tsx", "Whiteboard", frames.relative_to(PROJECT), "--sequence", "--image-format=jpeg",
                 "--jpeg-quality=92", f"--props={props}", "--concurrency=1", f"--browser-executable={CHROME}", "--log=info"],
                cwd=PROJECT, log_file=workdir / "log.txt", env=utf8_env(REMOTION_DISABLE_TELEMETRY="1"), timeout=1800)
            first = re.fullmatch(r"(.*?)(\d+)\.jpe?g", min(path.name for path in frames.glob("*.jp*g")))
            log("ghép khung hình + giọng đọc bằng ffmpeg")
            run(["ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-start_number", str(int(first[2])),
                 "-i", frames / f"{first[1]}%0{len(first[2])}d{Path(first[0]).suffix}", "-i", wav,
                 "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out],
                cwd=workdir, log_file=workdir / "log.txt")
            return out
        finally:
            (workdir / "narration.wav").unlink(missing_ok=True)
            shutil.rmtree(beat_dir, ignore_errors=True)
