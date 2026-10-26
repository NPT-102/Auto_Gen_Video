"""Whiteboard video: render each narrated beat through Whiteboard Lab, then
use a separate Remotion project for captions, transitions and final audio."""

import json
import os
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
# Chrome tabs Remotion renders with. Frames are independent stills, so a few tabs cut the render time several-fold
# (35 s demo: ~100 s with one tab); WHITEBOARD_CONCURRENCY=1 restores the old behaviour on a small machine.
RENDER_CONCURRENCY = int(os.environ.get("WHITEBOARD_CONCURRENCY") or max(1, min(6, (os.cpu_count() or 2) // 4)))

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


def lab_caps() -> dict:
    """What the selected Lab can do beyond the original command line (engines/whiteboard-lab declares it).

    frames_dir: writes transparent PNG frames itself, so no MP4 -> colour-keyed PNG round trip;
    pen_json: also writes the pen-tip path, so Remotion can draw one hand that travels between objects;
    natural: picks a human drawing speed up to the window instead of stretching every object over it."""
    try:
        return json.loads((WHITEBOARD_LAB_DIR / "lab" / "capabilities.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


WRITING_KINDS = {"text", "stat", "formula"}   # drawn left to right like handwriting


def planned_draw_mode(requested: str, planned: bool, layer: dict, fallback: str) -> str:
    """Use direct ink only when the generated layer is genuinely pen-thin.

    The planner marks arrows and simple labels as direct colour.  An icon with
    an interior to paint (phone screen, lock body, shield, chart bar) keeps
    outline then colour.  Explicit user modes always win.
    """
    if requested != "auto" or not planned:
        return fallback
    selected = str(layer.get("draw_mode") or "")
    if selected == "direct_color":
        return "direct_ink"
    if selected == "outline_color":
        return selected
    return "direct_ink" if layer.get("kind") in WRITING_KINDS else fallback


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


def estimate_layer_complexity(python: Path, source: Path, draw_mode: str, workdir: Path) -> float | None:
    """Ask a compatible Lab how much visible drawing work a layer contains.

    A layer's bounding box says almost nothing about its drawing time: a large
    circle can be quick, while compact text or a detailed doodle needs many
    more pen movements.  The estimate is cheap and happens before rendering.
    """
    raw = run([python, "-m", "lab.module", "--image", source, "--estimate", "--mode", draw_mode],
              cwd=WHITEBOARD_LAB_DIR, log_file=workdir / "log.txt", env=utf8_env(),
              timeout=120, capture_stdout=True)
    try:
        value = float(json.loads(raw.strip().splitlines()[-1])["cost"])
        return value if value > 0 else None
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def layer_durations(seconds: float, layers: list[dict]) -> list[float] | None:
    """Give every object a visible drawing window, or choose one whole scene."""
    minimum = 0.75
    if not layers or len(layers) * minimum > seconds:
        return None
    remaining = max(0.0, seconds - len(layers) * minimum)
    # `complexity` comes from the Lab's actual pixels (contours + paint), not
    # from the rectangle in which an object happens to be positioned.
    weights = [max(0.01, float(layer.get("complexity", layer.get("weight", 1)))) for layer in layers]
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
    def sequential(durations: list[float], leading: float = 0.0) -> list[tuple[float, float]]:
        return [(leading + sum(durations[:i]), duration) for i, duration in enumerate(durations)]

    durations = layer_durations(seconds, layers)
    if durations is None:
        return None
    requested: list[float] = []
    for layer in layers:
        value = layer.get("at")
        if value is None:
            return sequential(durations)
        try:
            value = float(value)
        except (TypeError, ValueError):
            return sequential(durations)
        requested.append(seconds * value if 0 <= value <= 1 else value)
    if requested != sorted(requested):
        return sequential(durations)

    # `at` is authored as the intended moment an item is mentioned in the
    # narration.  It used to force the next `at` into a hard deadline, which
    # made a dense small drawing rush and a sparse large one crawl.  Retain a
    # deliberate opening gap and reveal the rest in the author-specified
    # order using the measured drawing work.  When the old timing happens to
    # leave a usable gap, preserve it without slowing a pen down.
    leading = min(max(0.0, requested[0]), seconds * 0.25)
    paced = layer_durations(seconds - leading, layers)
    if paced is None:
        return sequential(durations)
    windows: list[tuple[float, float]] = []
    cursor = leading
    for desired, duration in zip(requested, paced):
        start = max(cursor, desired)
        windows.append((start, duration))
        cursor = start + duration
    # A later explicit cue may consume spare time. If doing so would clip the
    # final drawing, prefer one continuous, naturally paced reveal.
    if cursor > seconds + 0.03:
        return sequential(paced, leading)
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
        layers = page["layers"]
        for index, layer in enumerate(layers):
            # The next layer is a transparent drawing on top of this
            # completed board.  When it finishes, its own cumulative still
            # takes over. Do not leave both cumulative stills visible or all
            # earlier marks are painted a second time.
            if index + 1 < len(layers):
                next_layer = layers[index + 1]
                # Remotion can only switch on integer frame boundaries.  Do
                # not derive this layer's end from a separately rounded
                # floating timestamp: that left one frame where the incoming
                # layer was still transparent and the finished board had
                # already vanished.  Hold through the exact frame where the
                # next layer's cumulative still takes over.
                next_from = round((float(next_layer["t0"]) - float(page["t0"])) * FPS)
                next_draw = round((float(next_layer["draw_t1"]) - float(next_layer["t0"])) * FPS)
                layer["hold_frame"] = next_from + max(1, next_draw)
                layer["hold_t1"] = round(float(page["t0"]) + layer["hold_frame"] / FPS, 3)
            else:
                layer["hold_t1"] = round(float(page["t1"]), 3)
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
                {**layer, "path": str(plan_dir / layer["file"]),
                 "alpha_path": str(plan_dir / layer["alpha_file"]) if layer.get("alpha_file") else None}
                for layer in rendered["layers"]
            ],
            "_planned_composite": str(plan_dir / rendered["composite"]),
            "_planned_composite_alpha": (str(plan_dir / rendered["composite_alpha"])
                                         if rendered.get("composite_alpha") else None),
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
        caps = lab_caps()
        try:
            # Completed layers are rendered as a cumulative transparent board.
            # A page reset starts a new board; objects on the same page persist.
            active_page = object()
            page_sources: list[Path] = []
            for index, beat in enumerate(data.get("beats", []), 1):
                page = beat.get("page", index)
                if page != active_page:
                    active_page = page
                    page_sources = []
                planned_layers = beat.pop("_planned_layers", None)
                planned_composite = beat.pop("_planned_composite", None)
                planned_composite_alpha = beat.pop("_planned_composite_alpha", None)
                source = PROJECT / "public" / beat["src"] if not planned_layers else None
                seconds = max(0.1, float(beat["t1"]) - float(beat["t0"]))
                objects_dir = beat_dir / "objects" / f"scene-{index:02d}"
                if planned_layers:
                    layers = [
                        {"file": None, "path": item["path"], "alpha": item.get("alpha_path"), "kind": item.get("kind"),
                         "color": item.get("color"), "weight": item.get("weight", 1.0),
                         "draw_mode": item.get("draw_mode"),
                         "bbox": item["bbox"], "at": item.get("at")}
                        for item in planned_layers
                    ]
                    fallback = False
                else:
                    manifest = split_scene_objects(python, source, objects_dir, workdir)
                    layers = list(manifest.get("layers") or [])
                    fallback = bool(manifest.get("fallback"))

                render_mode = "outline_color" if planned_layers and mode == "auto" else mode
                if caps.get("complexity"):
                    for layer in layers:
                        layer_source = (Path(layer["path"]) if layer.get("path") else
                                        source if layer.get("file") is None else objects_dir / layer["file"])
                        # An estimate failure is non-fatal: the legacy planner
                        # weight remains a sensible fallback for that layer.
                        try:
                            layer_mode = planned_draw_mode(mode, bool(planned_layers), layer, render_mode)
                            complexity = estimate_layer_complexity(python, layer_source, layer_mode, workdir)
                        except Exception as exc:
                            log(f"whiteboard: khÃ´ng Ä‘o Ä‘Æ°á»£c Ä‘á»™ phức táº¡p layer ({exc}); dÃ¹ng timing dá»± phÃ²ng")
                            complexity = None
                        if complexity is not None:
                            layer["complexity"] = complexity
                schedule = layer_schedule(seconds, layers)
                # A short narration line cannot show six separate drawings
                # clearly. Keep the original whole composition in that case,
                # rather than silently dropping smaller objects.
                if schedule is None:
                    layers = [{"file": None, "path": planned_composite, "alpha": planned_composite_alpha,
                               "weight": 1.0, "bbox": {"x": 0, "y": 0, "w": 1, "h": 1}}]
                    schedule = [(0.0, seconds)]
                    fallback = True

                log(f"whiteboard part {index}/{len(data['beats'])}: {len(layers)} layer(s), {seconds:.1f}s ({render_mode})")
                rendered_layers = []
                for layer_index, (layer, (offset, draw_seconds)) in enumerate(zip(layers, schedule), 1):
                    layer_source = (Path(layer["path"]) if layer.get("path") else
                                    source if layer["file"] is None else objects_dir / layer["file"])
                    target = clips / f"wb{index:02d}-{layer_index:02d}.mp4"
                    frame_dir = target.with_name(f"{target.stem}-frames")
                    pen = None
                    drawn_seconds = draw_seconds
                    layer_mode = planned_draw_mode(mode, bool(planned_layers), layer, render_mode)
                    if caps.get("frames_dir"):
                        # The bundled Lab draws straight from the transparent layer into transparent frames (no
                        # hand); its pen path drives one hand in Remotion that travels between objects.
                        image = Path(layer["alpha"]) if layer.get("alpha") else layer_source
                        pen_file = target.with_name(f"{target.stem}-pen.json")
                        order = "writing" if layer.get("kind") in WRITING_KINDS else "auto"
                        command = [python, "-m", "lab.module", "--image", image, "--frames-dir", frame_dir,
                                   "--pen-json", pen_file, "--duration", f"{draw_seconds:.3f}",
                                   "--mode", layer_mode]
                        # Text benefits from a short intrinsic writing speed.
                        # Icons need their scene allocation; applying the
                        # same cap to a phone made it finish in about a second.
                        if caps.get("natural") and layer.get("kind") in WRITING_KINDS:
                            command.append("--natural")
                        if caps.get("order"):
                            command.extend(["--order", order])
                        raw = run(command,
                                  cwd=WHITEBOARD_LAB_DIR, log_file=workdir / "log.txt", env=utf8_env(), timeout=1800,
                                  capture_stdout=True)
                        try:
                            info = json.loads(raw.strip().splitlines()[-1])
                            frame_count, drawn_seconds = int(info["frames"]), float(info["duration"])
                            pen = json.loads(pen_file.read_text(encoding="utf-8"))["points"]
                        except (IndexError, KeyError, ValueError, OSError, json.JSONDecodeError) as exc:
                            raise RuntimeError("Whiteboard Lab did not return frames and a pen path") from exc
                        layer_source = image
                    else:
                        run([python, "-m", "lab.module", "--image", layer_source, "--output", target,
                             "--duration", f"{draw_seconds:.3f}", "--mode", layer_mode],
                            cwd=WHITEBOARD_LAB_DIR, log_file=workdir / "log.txt", env=utf8_env(), timeout=1800)
                        raw = run([python, ROOT / "tools" / "make_transparent_frames.py", target, frame_dir],
                                  cwd=ROOT, log_file=workdir / "log.txt", env=utf8_env(), timeout=300,
                                  capture_stdout=True)
                        try:
                            frame_count = int(json.loads(raw.strip().splitlines()[-1])["frames"])
                        except (IndexError, KeyError, ValueError, json.JSONDecodeError) as exc:
                            raise RuntimeError("transparent whiteboard frame conversion failed") from exc
                    # Use one transparent, cumulative board after the drawing
                    # ends. A single new source layer has opaque paper, which
                    # otherwise erases the earlier drawings below it.
                    page_sources.append(layer_source)
                    still = target.with_name(f"{target.stem}-still.png")
                    run([python, ROOT / "tools" / "make_transparent_layer.py", *page_sources, "--output", still],
                        cwd=ROOT, log_file=workdir / "log.txt", env=utf8_env(), timeout=120)
                    draw_start = float(beat["t0"]) + offset
                    draw_end = min(float(beat["t1"]), draw_start + drawn_seconds)
                    rendered_layers.append({
                        "t0": round(draw_start, 3), "draw_t1": round(draw_end, 3),
                        "hold_t1": round(float(beat["t1"]), 3),
                        "clip": f"jobs/{job}/whiteboard/{target.name}",
                        "frames": f"jobs/{job}/whiteboard/{frame_dir.name}",
                        "frame_count": frame_count,
                        "still": f"jobs/{job}/whiteboard/{still.name}",
                        "bbox": layer["bbox"],
                        "blend": "normal",
                        **({"pen": pen} if pen else {}),
                    })
                beat["layers"] = rendered_layers
                beat.pop("clip", None)

            data["whiteboard_pages"] = assemble_pages(data.get("beats", []))
            wav = workdir / "narration.wav"
            # Voice (and music from assets/music) only. No template sound effects: their pops follow bullet/stat cues
            # the whiteboard never draws, and their whoosh fires on every scene even when the page does not change.
            build_audio(parts, wav, None, spec.title)
            props = workdir / "props.json"
            props.write_text(json.dumps({"data": data, "audio": ""}, ensure_ascii=False), encoding="utf-8")
            out, frames = workdir / "video.mp4", beat_dir / "frames"
            shutil.rmtree(frames, ignore_errors=True)
            log(f"Remotion ghép {len(data.get('beats', []))} cảnh whiteboard, {data['duration']:.0f}s")
            run(["node", CLI, "render", "src/index.tsx", "Whiteboard", frames.relative_to(PROJECT), "--sequence", "--image-format=jpeg",
                 "--jpeg-quality=92", f"--props={props}", f"--concurrency={RENDER_CONCURRENCY}",
                 f"--browser-executable={CHROME}", "--log=info"],
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
