from datetime import timezone

from bot.parlays import timeutils


def test_parse_utc_handles_z_suffix():
    dt = timeutils.parse_utc("2026-08-29T19:00:00Z")
    assert dt.year == 2026
    assert dt.tzinfo is not None


def test_parse_utc_handles_milliseconds_and_z_suffix():
    dt = timeutils.parse_utc("2026-08-29T19:00:00.000Z")
    assert dt.hour == 19


def test_utc_now_is_timezone_aware():
    now = timeutils.utc_now()
    assert now.tzinfo == timezone.utc
