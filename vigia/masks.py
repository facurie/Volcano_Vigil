"""COCO run-length encoding of boolean masks.

The format of pycocotools and of meta_sam_parser.decode_mask_to_rle: pixels in
column-major order, alternating runs of 0s and 1s that start with 0s, and the
run lengths packed into a string (5 bits per character plus a continuation
bit, offset 48; each run after the second is stored as the difference from
the run two before it).
"""

from __future__ import annotations

from typing import Any

import numpy as np


def encode(mask: np.ndarray) -> dict[str, Any]:
    """{"size": [height, width], "counts": "..."} for a 2-D boolean mask."""
    height, width = mask.shape
    flat = np.asarray(mask, dtype=bool).ravel(order="F")
    starts = np.flatnonzero(flat[1:] != flat[:-1]) + 1
    runs = np.diff(np.concatenate(([0], starts, [flat.size]))).tolist()
    if flat.size and flat[0]:
        runs.insert(0, 0)
    return {"size": [height, width], "counts": _to_string(runs)}


def decode(rle: dict[str, Any]) -> np.ndarray:
    """The boolean mask of an RLE made by `encode` (or by pycocotools)."""
    height, width = rle["size"]
    runs = _from_string(rle["counts"])
    if sum(runs) != height * width:
        raise ValueError(f"RLE runs cover {sum(runs)} pixels, not {height}x{width}")
    values = np.zeros(len(runs), dtype=bool)
    values[1::2] = True
    return np.repeat(values, runs).reshape((width, height)).T


def _to_string(runs: list[int]) -> str:
    chars = []
    for i, run in enumerate(runs):
        value = run - runs[i - 2] if i > 2 else run
        more = True
        while more:
            chunk = value & 0x1F
            value >>= 5
            more = value != -1 if chunk & 0x10 else value != 0
            if more:
                chunk |= 0x20
            chars.append(chr(chunk + 48))
    return "".join(chars)


def _from_string(counts: str) -> list[int]:
    runs: list[int] = []
    position = 0
    while position < len(counts):
        value, shift, more = 0, 0, True
        while more:
            chunk = ord(counts[position]) - 48
            value |= (chunk & 0x1F) << (5 * shift)
            more = bool(chunk & 0x20)
            position += 1
            shift += 1
            if not more and chunk & 0x10:
                value |= -1 << (5 * shift)
        if len(runs) > 2:
            value += runs[-2]
        runs.append(value)
    return runs
