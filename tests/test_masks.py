import numpy as np
import pytest
from meta_sam_parser import CompletedOutcome, decode_mask_to_raster, decode_mask_to_rle, image_segmentation_format

from test_sam import IMAGE_OUTPUT
from vigia.masks import decode, encode


def sam_masks():
    """The mask records of the docs' sample SAM output."""
    parser = image_segmentation_format().create_parser()
    for _ in parser.push(IMAGE_OUTPUT):
        pass
    return [record.mask for record in parser.finish(CompletedOutcome()).result.records if record.kind == "mask"]


def test_encode_matches_the_sam_parser_rle():
    for mask in sam_masks():
        raster = np.frombuffer(decode_mask_to_raster(mask), dtype=np.uint8).reshape(mask.height, mask.width)
        expected = decode_mask_to_rle(mask)

        assert encode(raster.astype(bool)) == {"size": list(expected.size), "counts": expected.counts}


@pytest.mark.parametrize("mask", [
    np.random.default_rng(1).random((37, 53)) > 0.6,
    np.ones((4, 5), dtype=bool),
    np.zeros((4, 5), dtype=bool),
    np.eye(6, dtype=bool),
    np.pad(np.ones((300, 200), dtype=bool), 50),
], ids=["random", "full", "empty", "diagonal", "large blob"])
def test_decode_reverses_encode(mask):
    decoded = decode(encode(mask))

    assert decoded.dtype == bool
    assert np.array_equal(decoded, mask)


def test_decode_rejects_runs_that_do_not_fill_the_size():
    counts = encode(np.ones((4, 5), dtype=bool))["counts"]

    with pytest.raises(ValueError, match="not 5x5"):
        decode({"size": [5, 5], "counts": counts})
