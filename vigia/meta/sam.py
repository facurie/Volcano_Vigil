"""SAM 3.1 output parsing.

SAM answers with special-token text, one line per frame, and base85 masks
covering each object's box. Meta's `meta_sam_parser` decodes the protocol;
this module turns its records into `SamObject`s with boolean numpy masks
scaled to their box.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from meta_sam_parser import (
    CompletedOutcome,
    decode_mask_to_raster,
    image_segmentation_format,
    video_segmentation_format,
)


class SamParseError(ValueError):
    """The SAM output text could not be parsed."""


@dataclass(frozen=True)
class SamObject:
    object_id: str  # stable across frames within one response
    frame_index: int | None  # None for images
    box: tuple[int, int, int, int]  # left, top, right, bottom: half-open source pixels
    score: float | None
    mask: np.ndarray  # bool, box-sized: (bottom - top) x (right - left)

    @property
    def area_px(self) -> int:
        return int(self.mask.sum())

    def full_mask(self, width: int, height: int) -> np.ndarray:
        full = np.zeros((height, width), dtype=bool)
        left, top, right, bottom = self.box
        full[top:bottom, left:right] = self.mask
        return full


def parse_output(text: str, *, video: bool = False) -> list[SamObject]:
    """Parse a complete SAM output text; an empty text means no matches."""
    fmt = video_segmentation_format() if video else image_segmentation_format()
    parser = fmt.create_parser()
    for _ in parser.push(text):
        pass
    result = parser.finish(CompletedOutcome()).result
    errors = [d.message for d in result.diagnostics if d.severity == "error"]
    if errors:
        raise SamParseError("; ".join(errors))

    objects = []
    for record in result.records:
        if record.kind != "mask":  # the box record repeats the mask's bounds
            continue
        bounds, mask = record.bounds, record.mask
        raster = np.frombuffer(decode_mask_to_raster(mask), dtype=np.uint8).reshape(mask.height, mask.width)
        objects.append(SamObject(
            object_id=record.object_id,
            frame_index=record.frame.frame_index if record.frame else None,
            box=(bounds.left, bounds.top, bounds.right, bounds.bottom),
            score=record.confidence,
            mask=_fit_to_box(raster.astype(bool), bounds.bottom - bounds.top, bounds.right - bounds.left),
        ))
    return objects


def _fit_to_box(raster: np.ndarray, height: int, width: int) -> np.ndarray:
    """Scale a mask raster to its box size, nearest neighbour.

    SAM sends large masks at reduced resolution (a 1081x680 px box came with a
    1024x644 raster), so the raster is not always box-sized.
    """
    if raster.shape == (height, width):
        return raster
    rows = ((np.arange(height) + 0.5) * raster.shape[0] / height).astype(int)
    cols = ((np.arange(width) + 0.5) * raster.shape[1] / width).astype(int)
    return raster[np.ix_(rows, cols)]
