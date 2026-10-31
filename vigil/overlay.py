"""Draw segmentation masks, outlines and boxes on a frame, with a legend strip below it."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFont

_LEGEND_BG = (25, 25, 25)
_LEGEND_FG = (240, 240, 240)
_PAD = 4


@dataclass(frozen=True)
class Layer:
    mask: np.ndarray  # bool, same height x width as the image
    color: tuple[int, int, int]
    label: str
    box: tuple[float, float, float, float] | None = None  # x0, y0, x1, y1 in pixels


def draw_layers(
    image: Image.Image,
    layers: Sequence[Layer],
    alpha: float = 0.45,
    *,
    min_legend_rows: int = 0,
    legend: bool = True,
) -> Image.Image:
    """Return a new RGB image with each layer's mask tinted and outlined.

    Labels go in a legend strip below the frame, one row per layer, so they
    never hide burned-in text (timestamps, PTZ readouts) or the top of a plume.
    `min_legend_rows` reserves rows even when there are fewer layers, so every
    frame rendered for one video gets the same size. With no layers and no
    reserved rows the output keeps the input's size. `legend=False` draws no strip at all, for pages that show
    their own legend.
    """
    pixels = np.asarray(image.convert("RGB"), dtype=np.float32).copy()
    height, width = pixels.shape[:2]
    for layer in layers:
        if layer.mask.shape != (height, width):
            raise ValueError(f"mask shape {layer.mask.shape} does not match image shape {(height, width)}")
        color = np.array(layer.color, dtype=np.float32)
        pixels[layer.mask] = (1 - alpha) * pixels[layer.mask] + alpha * color
        pixels[_edge(layer.mask)] = color

    frame = Image.fromarray(pixels.round().astype(np.uint8))
    draw = ImageDraw.Draw(frame)
    for layer in layers:
        if layer.box:
            draw.rectangle(layer.box, outline=layer.color, width=max(1, height // 400))
    rows = max(len(layers), min_legend_rows) if legend else 0
    return _add_legend(frame, layers, rows) if rows else frame


def _add_legend(frame: Image.Image, layers: Sequence[Layer], rows: int) -> Image.Image:
    """Return the frame with a legend strip of `rows` rows appended below it."""
    font = ImageFont.load_default(size=max(12, frame.height // 40))
    ascent, descent = font.getmetrics()
    swatch = ascent + descent
    line_h = swatch + _PAD
    out = Image.new("RGB", (frame.width, frame.height + rows * line_h + _PAD), _LEGEND_BG)
    out.paste(frame, (0, 0))
    draw = ImageDraw.Draw(out)
    for i, layer in enumerate(layers):
        top = frame.height + _PAD + i * line_h
        draw.rectangle((_PAD, top, _PAD + swatch, top + swatch), fill=layer.color)
        draw.text((3 * _PAD + swatch, top), layer.label, fill=_LEGEND_FG, font=font)
    return out


def _edge(mask: np.ndarray) -> np.ndarray:
    """Mask pixels with at least one 4-neighbour outside the mask."""
    interior = mask.copy()
    interior[1:, :] &= mask[:-1, :]
    interior[:-1, :] &= mask[1:, :]
    interior[:, 1:] &= mask[:, :-1]
    interior[:, :-1] &= mask[:, 1:]
    return mask & ~interior
