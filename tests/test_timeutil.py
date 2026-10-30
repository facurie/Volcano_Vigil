from datetime import datetime, timezone

import pytest

from vigil.timeutil import parse_utc, to_iso


def test_parse_utc_reads_a_z_suffix_without_seconds():
    assert parse_utc("2026-10-17T13:00Z") == datetime(2026, 10, 17, 13, 0, tzinfo=timezone.utc)


def test_parse_utc_converts_other_offsets_to_utc():
    parsed = parse_utc("2026-10-17T03:19-10:00")

    assert parsed == datetime(2026, 10, 17, 13, 19, tzinfo=timezone.utc)
    assert parsed.tzinfo == timezone.utc


def test_parse_utc_reads_back_what_to_iso_writes():
    moment = datetime(2026, 10, 17, 14, 50, 5, tzinfo=timezone.utc)

    assert parse_utc(to_iso(moment)) == moment


def test_parse_utc_rejects_a_time_without_offset():
    with pytest.raises(ValueError, match="offset"):
        parse_utc("2026-10-17T13:00")
