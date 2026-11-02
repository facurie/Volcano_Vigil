import io

import numpy as np
import pytest
from PIL import Image

from conftest import make_textured_jpeg
from vigil.calibration import Framing, FramingReference
from vigil.framing import MAX_SHIFT, MIN_PEAK, foot, match, signature

FRAMING = Framing(references=[FramingReference(path="refs/day.jpg", sha256="0" * 64)], rows_from=0.5,
                  skip_columns=(0.4, 0.6))


def image(**kwargs):
    return Image.open(io.BytesIO(make_textured_jpeg(**kwargs)))


def compare(reference, frame):
    return match(signature(reference, FRAMING)[0], signature(frame, FRAMING)[0])


def test_a_frame_keeps_its_own_framing():
    found = compare(image(seed=1), image(seed=1))

    assert found.same and (found.dx, found.dy) == (0, 0) and found.peak > 0.5


def test_a_shift_within_max_shift_keeps_the_framing():
    assert compare(image(seed=1), image(seed=1, shift=(MAX_SHIFT, -1))).same


def test_a_shift_beyond_max_shift_does_not_and_is_measured():
    found = compare(image(seed=1), image(seed=1, shift=(0, 6)))

    assert not found.same
    assert abs(found.dy) == 6 and found.dx == 0


@pytest.mark.parametrize("zoom", [1.05, 0.95])
def test_a_zoom_does_not_keep_the_framing(zoom):
    assert not compare(image(seed=1), image(seed=1, zoom=zoom)).same


def test_another_scene_does_not_keep_the_framing():
    found = compare(image(seed=1), image(seed=2))

    assert not found.same and found.peak < MIN_PEAK


def test_rows_above_rows_from_and_the_skipped_columns_are_left_out():
    reference = np.asarray(image(seed=1)).copy()
    frame = reference.copy()
    frame[:250] = 255                    # the sky: above rows_from (0.5 of 540 rows)
    frame[300:, 400:560] = 0             # inside skip_columns (0.4-0.6 of 960 columns): the vent
    found = match(signature(Image.fromarray(reference), FRAMING)[0], signature(Image.fromarray(frame), FRAMING)[0])

    assert found.same and found.peak > 0.5


def test_signature_gives_the_mean_brightness():
    _, bright = signature(image(seed=1, brightness=0.2), FRAMING)

    assert 15 < bright < 35


def test_a_masks_foot_is_the_middle_of_its_lowest_rows():
    mask = np.zeros((50, 40), dtype=bool)
    mask[0:50, 18:22] = True             # the jet
    mask[48:50, 10:30] = True            # its spreading base

    assert foot(mask, left=100, top=200).tolist() == pytest.approx([100 + 19.5, 200 + 49])


def test_an_empty_mask_has_no_foot():
    assert foot(np.zeros((5, 5), dtype=bool), 0, 0) is None
