"""Turn a whiteboard layer's paper background into transparency.

The drawing engine needs an opaque paper image while it draws.  The video
compositor needs the completed object only, otherwise every new layer erases
the objects already on the board.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image


def as_transparent_layer(source: Path) -> Image.Image:
    image = Image.open(source).convert("RGBA")
    pixels = np.asarray(image).copy()
    rgb = pixels[..., :3].astype(np.int16)
    # Whiteboard paper is near white. Keep anti-aliased dark/coloured edges;
    # only the paper itself becomes transparent.
    paper = (rgb[..., 0] >= 242) & (rgb[..., 1] >= 242) & (rgb[..., 2] >= 238)
    pixels[..., 3][paper] = 0
    return Image.fromarray(pixels, "RGBA")


def compose(sources: list[Path], output: Path) -> None:
    layers = [as_transparent_layer(source) for source in sources]
    if not layers:
        raise ValueError("at least one source layer is required")
    canvas = Image.new("RGBA", layers[0].size, (0, 0, 0, 0))
    for layer in layers:
        if layer.size != canvas.size:
            raise ValueError("all whiteboard layers must have the same size")
        canvas.alpha_composite(layer)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("sources", type=Path, nargs="+")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    compose(args.sources, args.output)


if __name__ == "__main__":
    main()
