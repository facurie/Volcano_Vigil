"""Meta Model API prices and per-call cost from the response `usage` block.

Prices from https://dev.meta.ai/docs/pricing-rate-limits, read 2026-10-26.
Unknown models raise instead of being logged as free.
"""

from __future__ import annotations

from typing import Any

# USD per token (Muse Spark) or per billed unit (SAM).
_TOKEN_PRICES = {
    "muse-spark-1.3": {"input": 1.25e-6, "cached": 0.15e-6, "output": 4.25e-6},
}
_SAM_PRICES = {
    # The 50-frame minimum per video request is already reflected in
    # usage.video_frames_processed, so no floor is applied here.
    "sam-3.1": {"image": 2.50e-3, "frame": 0.20e-3},
}


def cost_usd(model: str, usage: dict[str, Any]) -> float:
    if model in _SAM_PRICES:
        price = _SAM_PRICES[model]
        return ((usage.get("images_processed") or 0) * price["image"]
                + (usage.get("video_frames_processed") or 0) * price["frame"])
    if model not in _TOKEN_PRICES:
        raise KeyError(f"no price configured for model {model!r}")
    price = _TOKEN_PRICES[model]
    cached = (usage.get("input_tokens_details") or {}).get("cached_tokens") or 0
    return ((usage.get("input_tokens", 0) - cached) * price["input"]
            + cached * price["cached"]
            + usage.get("output_tokens", 0) * price["output"])
