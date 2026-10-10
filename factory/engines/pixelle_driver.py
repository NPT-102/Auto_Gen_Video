"""Chạy pipeline chuẩn của Pixelle-Video trong venv của Pixelle, mỗi câu gắn sẵn một ảnh (Pexels) thay cho model vẽ ảnh.

    engines/pixelle-video/.venv/Scripts/python.exe factory/engines/pixelle_driver.py job.json   (cwd = engines/pixelle-video)

job.json: {text, title, frame_template, voice_id, template_params, images: [đường dẫn ảnh | null, ...]} — text có các câu
cách nhau bởi dòng trống (chế độ "fixed": mỗi đoạn một khung), images cùng thứ tự.
audio (tuỳ chọn): [{path, duration}] cùng thứ tự; có audio thì Pixelle không gọi Edge TTS.
Dòng cuối stdout: {"video": "..."}.
File này chỉ import pixelle_video và thư viện chuẩn (chạy trong venv khác với factory).
"""

import asyncio
import json
import sys
from pathlib import Path

from pixelle_video.pipelines.standard import StandardPipeline
from pixelle_video.service import PixelleVideoCore
from pixelle_video.services.frame_html import HTMLFrameGenerator
from pixelle_video.utils.template_util import resolve_template_path


class PhotoPipeline(StandardPipeline):
    """Bỏ bước viết mô tả ảnh và vẽ ảnh: frame_processor thấy khung đã có image_path thì dùng luôn ảnh đó."""

    def __init__(self, core, images: list[str | None], audio: list[dict] | None = None):
        super().__init__(core)
        self.images = images
        self.audio = audio

    async def plan_visuals(self, ctx):
        ctx.image_prompts = [None] * len(ctx.narrations)

    async def initialize_storyboard(self, ctx):
        await super().initialize_storyboard(ctx)
        frames = ctx.storyboard.frames
        if self.audio is not None:
            if len(frames) != len(self.audio):
                raise ValueError(f"{len(frames)} khung nhưng {len(self.audio)} đoạn giọng VieNeu")
            for frame, audio in zip(frames, self.audio):
                frame.audio_path, frame.duration = audio["path"], audio["duration"]
        if len(frames) != len(self.images):
            print(f"cảnh báo: {len(frames)} khung nhưng {len(self.images)} ảnh", file=sys.stderr)
        for i, frame in enumerate(frames):
            img = self.images[min(i, len(self.images) - 1)] if self.images else None
            if img:
                frame.image_path, frame.media_type = img, "image"


async def main(job_file: str) -> None:
    job = json.loads(Path(job_file).read_text(encoding="utf-8"))
    core = PixelleVideoCore("config.yaml")
    await core.initialize()
    try:
        width, height = HTMLFrameGenerator(resolve_template_path(job["frame_template"])).get_media_size()
        result = await PhotoPipeline(core, job["images"], job.get("audio"))(
            text=job["text"], mode="fixed", title=job["title"], media_width=width, media_height=height, video_fps=30,
            frame_template=job["frame_template"], voice_id=job["voice_id"], template_params=job["template_params"],
            bgm_path=None)
    finally:
        await core.cleanup()
    print(json.dumps({"video": str(result.video_path)}))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
