"""Prepare frames for the Meta Model API."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageOps

MAX_SIDE_PX = 2048  # larger frames are downscaled before upload; SAM masks refer to the sent image


def load_for_upload(path: str | Path, max_side: int = MAX_SIDE_PX) -> tuple[Image.Image, bytes]:
    """Load a frame as displayed (EXIF rotation applied), cap its longest side and encode it as JPEG.

    Returns the image that was encoded too, so masks can be drawn on it.
    """
    with Image.open(path) as raw:
        image = ImageOps.exif_transpose(raw).convert("RGB")
    image.thumbnail((max_side, max_side))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    return image, buffer.getvalue()
