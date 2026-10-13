import pytest

from healthviz.archive.values import (
    local_date,
    number,
    offset_text,
    parse_offset,
    parse_utc,
    positive,
    utc_iso,
)


def test_utc_round_trip():
    assert utc_iso(1767225600) == "2026-01-01T00:00:00Z"
    assert parse_utc("2026-01-01T00:00:00Z") == 1767225600


@pytest.mark.parametrize("minutes,text", [(120, "+02:00"), (-330, "-05:30"), (0, "+00:00")])
def test_offsets(minutes, text):
    assert offset_text(minutes) == text
    assert parse_offset(text) == minutes


def test_local_day():
    assert local_date("2026-01-01T23:30:00Z", "+02:00") == "2026-01-02"
    assert local_date("2026-01-01T00:30:00Z", "-05:00") == "2025-12-31"


def test_numbers():
    assert number(7) == "7"
    assert number(65.0) == "65.0"
    assert number(91.899994) == "91.9"
    assert number(None) == ""
    assert positive(0) == ""
    assert positive(12) == "12"


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf"])
def test_nonfinite_rejected(bad):
    with pytest.raises(ValueError):
        number(float(bad))
