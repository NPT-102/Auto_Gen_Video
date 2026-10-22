"""Convert a Whiteboard Lab MP4 into transparent PNG frames.

Lab intentionally renders on opaque paper.  Remotion needs the drawing and
the hand without that paper so it can place several drawings on one board.
PNG frames preserve alpha reliably in Chromium; alpha video codecs do not.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def background_colour(frame: np.ndarray) -> np.ndarray:
    h, w = frame.shape[:2]
    size = max(12, min(h, w) // 18)
    corners = np.concatenate((
        frame[:size, :size].reshape(-1, 3),
        frame[:size, w - size:].reshape(-1, 3),
        frame[h - size:, :size].reshape(-1, 3),
        frame[h - size:, w - size:].reshape(-1, 3),
    ))
    return np.median(corners, axis=0)


def convert(video: Path, output: Path) -> int:
    output.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open whiteboard video: {video}")
    count = 0
    while True:
        ok, bgr = cap.read()
        if not ok:
            break
        background = background_colour(bgr)
        # Keep coloured/ink pixels and make paper transparent. The soft band
        # avoids a hard halo around anti-aliased strokes and the hand.
        distance = np.max(np.abs(bgr.astype(np.float32) - background), axis=2)
        alpha = np.clip((distance - 3.0) * (255.0 / 15.0), 0, 255).astype(np.uint8)
        bgra = np.dstack((bgr, alpha))
        path = output / f"frame-{count:05d}.png"
        if not cv2.imwrite(str(path), bgra):
            raise RuntimeError(f"cannot write frame: {path}")
        count += 1
    cap.release()
    if not count:
        raise RuntimeError("whiteboard video contains no frames")
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps({"frames": convert(args.video, args.output)}))


if __name__ == "__main__":
    main()
