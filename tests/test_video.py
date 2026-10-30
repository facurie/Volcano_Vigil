import shutil
import subprocess

import pytest

from vigil.video import assemble, cut_clip, extract_frames, probe

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    path = tmp_path_factory.mktemp("video") / "source.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25", "-t", "4",
         "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )
    return path


def test_probe_reports_size_fps_and_frame_count(source):
    info = probe(source)

    assert (info.width, info.height) == (320, 240)
    assert info.fps == pytest.approx(25)
    assert info.frames == 100


def test_cut_clip_trims_resamples_and_scales(source, tmp_path):
    clip = cut_clip(source, tmp_path / "clip.mp4", start_s=1.0, duration_s=2.0, fps=10, height=120)

    info = probe(clip)
    assert (info.width, info.height) == (160, 120)
    assert info.fps == pytest.approx(10)
    assert info.frames == 20


def test_extract_frames_writes_one_image_per_frame_in_order(source, tmp_path):
    clip = cut_clip(source, tmp_path / "clip.mp4", start_s=0, duration_s=1.0, fps=5, height=120)

    frames = extract_frames(clip, tmp_path / "frames")

    assert [f.name for f in frames] == [f"{i:05d}.jpg" for i in range(5)]


def test_assemble_turns_frames_back_into_a_video(source, tmp_path):
    clip = cut_clip(source, tmp_path / "clip.mp4", start_s=0, duration_s=1.0, fps=5, height=120)
    frames = extract_frames(clip, tmp_path / "frames")

    out = assemble(frames, tmp_path / "out.mp4", fps=5)

    info = probe(out)
    assert info.frames == 5
    assert info.fps == pytest.approx(5)


def test_assemble_can_scale_to_a_height(source, tmp_path):
    clip = cut_clip(source, tmp_path / "clip.mp4", start_s=0, duration_s=1.0, fps=5, height=240)
    frames = extract_frames(clip, tmp_path / "frames")

    info = probe(assemble(frames, tmp_path / "out.mp4", fps=5, height=120))

    assert (info.width, info.height, info.frames) == (160, 120, 5)
