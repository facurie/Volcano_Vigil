import pytest

from vigia.meta.pricing import cost_usd


def test_muse_spark_cost_uses_input_and_output_token_rates():
    usage = {"input_tokens": 2000, "output_tokens": 500}

    assert cost_usd("muse-spark-1.3", usage) == pytest.approx(2000 * 1.25e-6 + 500 * 4.25e-6)


def test_cached_input_tokens_are_billed_at_the_cached_rate():
    usage = {"input_tokens": 2000, "input_tokens_details": {"cached_tokens": 1000}, "output_tokens": 0}

    assert cost_usd("muse-spark-1.3", usage) == pytest.approx(1000 * 1.25e-6 + 1000 * 0.15e-6)


def test_sam_image_calls_are_billed_per_image():
    assert cost_usd("sam-3.1", {"images_processed": 1}) == pytest.approx(0.0025)


def test_sam_video_calls_are_billed_per_processed_frame():
    assert cost_usd("sam-3.1", {"video_frames_processed": 120}) == pytest.approx(0.024)


def test_unknown_models_are_rejected_instead_of_logged_as_free():
    with pytest.raises(KeyError, match="muse-wonder"):
        cost_usd("muse-wonder-1.0", {"input_tokens": 10, "output_tokens": 10})
