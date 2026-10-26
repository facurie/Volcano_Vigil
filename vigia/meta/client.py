"""Meta Model API client: Muse Spark and SAM 3.1 through the OpenAI SDK.

Every call is checked against the daily budget before it is sent and logged
to the cost ledger afterwards, including failures.
"""

from __future__ import annotations

import base64
import json
import os
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import openai

from vigia.meta.ledger import CostLedger
from vigia.meta.pricing import cost_usd
from vigia.meta.sam import SamObject, parse_output

DEFAULT_BASE_URL = "https://api.meta.ai/v1"
SPARK_MODEL = "muse-spark-1.3"
SAM_MODEL = "sam-3.1"

# Upper-bound guesses for the pre-call budget check (docs: ~1,300-1,500
# tokens for a ~1280 px image; SAM bills at least 50 frames per video).
_IMAGE_TOKENS_ESTIMATE = 1600
_PROMPT_OVERHEAD_TOKENS = 200
_SAM_MIN_BILLED_FRAMES = 50


class MissingApiKey(RuntimeError):
    """MODEL_API_KEY is not configured."""


class SamStreamError(RuntimeError):
    """A streamed SAM response failed or ended early."""


class MetaClient:
    def __init__(
        self,
        sdk: openai.OpenAI,
        ledger: CostLedger,
        *,
        spark_model: str = SPARK_MODEL,
        sam_model: str = SAM_MODEL,
    ):
        self._sdk = sdk
        self._ledger = ledger
        self.spark_model = spark_model
        self.sam_model = sam_model

    @classmethod
    def from_env(cls, ledger: CostLedger) -> MetaClient:
        api_key = os.getenv("MODEL_API_KEY")
        if not api_key:
            raise MissingApiKey("MODEL_API_KEY is not set; add it to .env")
        sdk = openai.OpenAI(
            base_url=os.getenv("META_API_BASE_URL", DEFAULT_BASE_URL),
            api_key=api_key,
            max_retries=0,  # retries would be billed calls the ledger never sees
            timeout=300,
        )
        return cls(
            sdk,
            ledger,
            spark_model=os.getenv("MUSE_SPARK_MODEL", SPARK_MODEL),
            sam_model=os.getenv("SAM_MODEL", SAM_MODEL),
        )

    def ask_json(
        self,
        *,
        prompt: str,
        schema_name: str,
        schema: dict[str, Any],
        purpose: str,
        images: Sequence[bytes] = (),
        instructions: str | None = None,
        effort: str = "low",
        max_output_tokens: int = 4000,
    ) -> dict[str, Any]:
        """Ask Muse Spark a question about zero or more images; the answer follows `schema`."""
        content = [{"type": "input_text", "text": prompt}]
        content += [{"type": "input_image", "image_url": _data_url(image)} for image in images]
        request: dict[str, Any] = {
            "model": self.spark_model,
            "input": [{"role": "user", "content": content}],
            "reasoning": {"effort": effort},
            "max_output_tokens": max_output_tokens,
            "text": {"format": {"type": "json_schema", "name": schema_name, "schema": schema, "strict": True}},
        }
        if instructions:
            request["instructions"] = instructions
        input_estimate = (len(images) * _IMAGE_TOKENS_ESTIMATE + _PROMPT_OVERHEAD_TOKENS
                          + (len(prompt) + len(instructions or "")) // 3)
        estimate = cost_usd(self.spark_model, {"input_tokens": input_estimate, "output_tokens": max_output_tokens})
        response = self._call(self.spark_model, purpose, estimate, lambda: self._sdk.responses.create(**request))
        return json.loads(response.output_text)

    def segment_image(self, image: bytes, phrase: str, *, purpose: str, mime: str = "image/jpeg") -> list[SamObject]:
        """Segment every instance of ONE noun phrase in an image."""
        content = [
            {"type": "input_text", "text": phrase},
            {"type": "input_image", "image_url": _data_url(image, mime)},
        ]
        estimate = cost_usd(self.sam_model, {"images_processed": 1})
        response = self._call(self.sam_model, purpose, estimate, lambda: self._sdk.responses.create(
            model=self.sam_model,
            input=[{"type": "message", "role": "user", "content": content}],
            metadata={"include_confidence": "true"},
        ))
        return parse_output(response.output_text or "")

    def upload_video(self, path: str | Path, expires_seconds: int = 3600) -> str:
        """Upload an MP4 to the Files API and return its file id."""
        with open(path, "rb") as fh:
            uploaded = self._sdk.files.create(
                file=fh,
                purpose="user_data",
                expires_after={"anchor": "created_at", "seconds": expires_seconds},
            )
        return uploaded.id

    def delete_file(self, file_id: str) -> None:
        self._sdk.files.delete(file_id)

    def segment_video(self, file_id: str, phrase: str, *, purpose: str, expected_frames: int) -> list[SamObject]:
        """Segment and track ONE noun phrase through an uploaded video, streaming frame by frame."""
        content = [
            {"type": "input_text", "text": phrase},
            {"type": "input_video", "file_id": file_id},
        ]
        chunks: list[str] = []

        def stream() -> Any:
            final = None
            events = self._sdk.responses.create(
                model=self.sam_model,
                input=[{"type": "message", "role": "user", "content": content}],
                metadata={"include_confidence": "true", "mask_encoding": "one_bit"},
                stream=True,
            )
            for event in events:
                if event.type == "response.output_text.delta":
                    chunks.append(event.delta)
                elif event.type == "response.completed":
                    final = event.response
                elif event.type in ("response.failed", "response.incomplete", "error"):
                    raise SamStreamError(f"SAM stream ended with {event.type}")
            if final is None:
                raise SamStreamError("SAM stream ended without response.completed")
            return final

        estimate = cost_usd(self.sam_model, {"video_frames_processed": max(expected_frames, _SAM_MIN_BILLED_FRAMES)})
        self._call(self.sam_model, purpose, estimate, stream)
        return parse_output("".join(chunks), video=True)

    def _call(self, model: str, purpose: str, estimate_usd: float, send: Callable[[], Any]) -> Any:
        self._ledger.ensure_budget(estimate_usd)
        started = time.perf_counter()
        try:
            response = send()
        except (openai.APIError, SamStreamError) as exc:
            self._ledger.record(model=model, purpose=purpose, cost_usd=0.0,
                                latency_ms=_elapsed_ms(started), error=_describe(exc))
            raise
        usage = response.usage.model_dump() if response.usage else {}
        self._ledger.record(
            model=model,
            purpose=purpose,
            cost_usd=cost_usd(model, usage),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            latency_ms=_elapsed_ms(started),
        )
        return response


def _data_url(data: bytes, mime: str = "image/jpeg") -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def _describe(exc: Exception) -> str:
    if isinstance(exc, openai.APIStatusError):
        return f"HTTP {exc.status_code}: {exc.message}"[:500]
    return f"{type(exc).__name__}: {exc}"[:500]
