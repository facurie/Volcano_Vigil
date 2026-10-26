"""Draw segmentation masks, outlines, boxes and a legend over a frame."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFont

_LEGEND_BG = (25, 25, 25)
_LEGEND_FG = (240, 240, 240)


@dataclass(frozen=True)
class Layer:
    mask: np.ndarray  # bool, same height x width as the image
    color: tuple[int, int, int]
    label: str
    box: tuple[float, float, float, float] | None = None  # x0, y0, x1, y1 in pixels


def draw_layers(image: Image.Image, layers: Sequence[Layer], alpha: float = 0.45) -> Image.Image:
    """Return a new RGB image with each layer's mask tinted and outlined.

    Labels go in a legend placed in the corner that covers the least mask
    area, so they never hide the top of a plume.
    """
    pixels = np.asarray(image.convert("RGB"), dtype=np.float32).copy()
    height, width = pixels.shape[:2]
    covered = np.zeros((height, width), dtype=bool)
    for layer in layers:
        if layer.mask.shape != (height, width):
            raise ValueError(f"mask shape {layer.mask.shape} does not match image shape {(height, width)}")
        color = np.array(layer.color, dtype=np.float32)
        pixels[layer.mask] = (1 - alpha) * pixels[layer.mask] + alpha * color
        pixels[_edge(layer.mask)] = color
        covered |= layer.mask

    out = Image.fromarray(pixels.round().astype(np.uint8))
    draw = ImageDraw.Draw(out)
    for layer in layers:
        if layer.box:
            draw.rectangle(layer.box, outline=layer.color, width=max(1, height // 400))
    if layers:
        _draw_legend(draw, layers, covered)
    return out


def _draw_legend(draw: ImageDraw.ImageDraw, layers: Sequence[Layer], covered: np.ndarray) -> None:
    height, width = covered.shape
    font = ImageFont.load_default(size=max(12, height // 40))
    pad = 4
    text_boxes = [draw.textbbox((0, 0), layer.label, font=font) for layer in layers]
    line_h = max(b[3] - b[1] for b in text_boxes) + pad
    swatch = line_h - pad
    panel_w = swatch + 3 * pad + max(b[2] - b[0] for b in text_boxes)
    panel_h = line_h * len(layers) + pad

    corners = [
        (pad, pad),
        (width - panel_w - pad, pad),
        (pad, height - panel_h - pad),
        (width - panel_w - pad, height - panel_h - pad),
    ]
    x, y = min(
        corners,
        key=lambda c: covered[max(0, c[1]):c[1] + panel_h, max(0, c[0]):c[0] + panel_w].sum(),
    )
    draw.rectangle((x, y, x + panel_w, y + panel_h), fill=_LEGEND_BG)
    for i, (layer, (left, top, _, _)) in enumerate(zip(layers, text_boxes)):
        row_y = y + pad + i * line_h
        draw.rectangle((x + pad, row_y, x + pad + swatch, row_y + swatch), fill=layer.color)
        draw.text((x + 2 * pad + swatch - left, row_y - top), layer.label, fill=_LEGEND_FG, font=font)


def _edge(mask: np.ndarray) -> np.ndarray:
    """Mask pixels with at least one 4-neighbour outside the mask."""
    interior = mask.copy()
    interior[1:, :] &= mask[:-1, :]
    interior[:-1, :] &= mask[1:, :]
    interior[:, 1:] &= mask[:, :-1]
    interior[:, :-1] &= mask[:, 1:]
    return mask & ~interior
