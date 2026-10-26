import numpy as np
import pytest

from vigia.meta.sam import SamParseError, parse_output

# Real sam-3.1 output published in the docs (320x334 source, lossless masks):
# https://dev.meta.ai/docs/sam/reading-segmentation (confidence values added by us)
OBJ_0 = ("0<|box;x1=211;y1=228;x2=270;y2=254;w=320;h=334;c=0.96|>"
         "<|mask;x=0;y=0;c=0.96;data=27,60,~!!!!M!0c[0o91w?q1!pIH4pPRVp2B3'7`e.ioeAf6-k/#Xd8%dX9x(|>")
OBJ_1 = ("1<|box;x1=155;y1=228;x2=202;y2=254;w=320;h=334;c=0.5|>"
         "<|mask;x=0;y=0;c=0.5;data=27,48,~!!!!J!0c[q=Pj_zs=*4C4(/./x#:/`S_GnD`=o3?X{emCgO$y@|>")
IMAGE_OUTPUT = f"<0f>{OBJ_0},{OBJ_1}"


def test_image_output_yields_one_object_per_match_with_half_open_boxes():
    objects = parse_output(IMAGE_OUTPUT)

    assert [o.object_id for o in objects] == ["0", "1"]
    assert objects[0].box == (211, 228, 271, 255)
    assert objects[0].frame_index is None
    assert objects[0].score == pytest.approx(0.96)


def test_masks_are_box_sized_boolean_rasters():
    obj = parse_output(IMAGE_OUTPUT)[0]

    assert obj.mask.dtype == bool
    assert obj.mask.shape == (27, 60)
    assert obj.area_px == 1539


def test_full_mask_places_the_raster_at_its_box():
    obj = parse_output(IMAGE_OUTPUT)[0]

    full = obj.full_mask(width=320, height=334)

    assert full.shape == (334, 320)
    assert full.sum() == obj.area_px
    assert np.array_equal(full[228:255, 211:271], obj.mask)


def test_empty_output_means_no_matches():
    assert parse_output("") == []


def test_video_output_keeps_frame_indices_and_stable_ids():
    text = f"<0f>{OBJ_0},{OBJ_1}\n<3f>{OBJ_0}\n"

    objects = parse_output(text, video=True)

    assert [(o.frame_index, o.object_id) for o in objects] == [(0, "0"), (0, "1"), (3, "0")]


def test_malformed_output_raises():
    with pytest.raises(SamParseError, match="Malformed"):
        parse_output("<0f>0<|box;x1=1;y1=2|>garbage")
