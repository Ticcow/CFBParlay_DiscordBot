from datetime import datetime, timezone

from bot.integrations.cfbd_client import CalendarWeek
from bot.scheduler import season


def test_season_year_for_fall_month():
    assert season.season_year_for(datetime(2026, 8, 17, tzinfo=timezone.utc)) == 2026


def test_season_year_for_early_year_month_is_previous_season():
    assert season.season_year_for(datetime(2027, 1, 5, tzinfo=timezone.utc)) == 2026


def make_week(week, start, end, season_type="regular"):
    return CalendarWeek(
        season=2026, week=week, season_type=season_type,
        first_game_start=start, last_game_start=end,
    )


CALENDAR = [
    make_week(1, "2026-08-25T00:00:00Z", "2026-08-31T23:59:00Z"),
    make_week(2, "2026-09-04T00:00:00Z", "2026-09-10T23:59:00Z"),
]


def test_determine_current_week_returns_in_progress_week():
    now = datetime(2026, 8, 28, tzinfo=timezone.utc)
    result = season.determine_current_week(CALENDAR, now)
    assert result.week == 1


def test_determine_current_week_falls_back_to_next_upcoming_during_gap():
    now = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)  # between week 1 and week 2
    result = season.determine_current_week(CALENDAR, now)
    assert result.week == 2


def test_determine_current_week_returns_none_once_season_is_over():
    now = datetime(2027, 2, 1, tzinfo=timezone.utc)
    assert season.determine_current_week(CALENDAR, now) is None


def test_determine_current_week_returns_none_for_empty_calendar():
    assert season.determine_current_week([], datetime(2026, 8, 28, tzinfo=timezone.utc)) is None
