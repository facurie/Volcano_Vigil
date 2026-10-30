"""ffmpeg helpers: probe videos, cut clips for SAM, and round-trip frames."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VideoInfo:
    width: int
    height: int
    fps: float
    frames: int
    duration_s: float


def probe(path: str | Path) -> VideoInfo:
    """Read size, frame rate and the exact (decoded) frame count of a video."""
    result = _run([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
        "-show_entries", "stream=width,height,avg_frame_rate,nb_read_frames:format=duration",
        "-of", "json", str(path),
    ])
    data = json.loads(result.stdout)
    stream = data["streams"][0]
    num, den = (float(x) for x in stream["avg_frame_rate"].split("/"))
    return VideoInfo(
        width=int(stream["width"]),
        height=int(stream["height"]),
        fps=num / den if den else 0.0,
        frames=int(stream["nb_read_frames"]),
        duration_s=float(data["format"]["duration"]),
    )


def cut_clip(
    src: str | Path,
    dst: str | Path,
    *,
    start_s: float,
    duration_s: float,
    fps: float,
    height: int,
) -> Path:
    """Cut, resample and scale a clip into an H.264 MP4 that SAM 3.1 accepts.

    SAM bills per frame, so `fps` directly sets the cost of segmenting it.
    """
    _run([
        "ffmpeg", "-v", "error", "-y", "-ss", str(start_s), "-i", str(src), "-t", str(duration_s),
        "-vf", f"fps={fps},scale=-2:{height}", "-an",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst),
    ])
    return Path(dst)


def extract_frames(video: str | Path, out_dir: str | Path) -> list[Path]:
    """Write every decoded frame as 00000.jpg, 00001.jpg, ... (SAM frame indices)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _run([
        "ffmpeg", "-v", "error", "-y", "-i", str(video), "-fps_mode", "passthrough",
        "-q:v", "2", "-start_number", "0", str(out_dir / "%05d.jpg"),
    ])
    return sorted(out_dir.glob("[0-9][0-9][0-9][0-9][0-9].jpg"))


def assemble(frames: Sequence[str | Path], dst: str | Path, *, fps: float, height: int | None = None) -> Path:
    """Encode an ordered list of same-sized images into an H.264 MP4.

    With `height` (even) the video is scaled to it, keeping the aspect ratio.
    """
    suffix = Path(frames[0]).suffix
    scale = f"scale=-2:{height}" if height else "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    with tempfile.TemporaryDirectory() as tmp:
        for i, frame in enumerate(frames):
            shutil.copyfile(frame, Path(tmp) / f"{i:05d}{suffix}")
        _run([
            "ffmpeg", "-v", "error", "-y", "-framerate", str(fps), "-start_number", "0",
            "-i", str(Path(tmp) / f"%05d{suffix}"),
            "-vf", scale,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst),
        ])
    return Path(dst)


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True)
