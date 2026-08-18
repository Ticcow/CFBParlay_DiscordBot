from datetime import datetime

from bot.integrations.cfbd_client import CalendarWeek
from bot.parlays import timeutils


def season_year_for(now: datetime) -> int:
    """CFBD numbers a season by the year it started in, even for January bowl
    games - e.g. a game on 2027-01-05 still belongs to the "2026" season."""
    return now.year - 1 if now.month <= 6 else now.year


def determine_current_week(
    calendar: list[CalendarWeek], now: datetime
) -> CalendarWeek | None:
    """Picks the week whose game window contains `now`, or - during the gap
    between one week's last game and the next week's first - the soonest
    upcoming week. Returns None once the season calendar has nothing left
    (off-season)."""
    for week in calendar:
        start = timeutils.parse_utc(week.first_game_start)
        end = timeutils.parse_utc(week.last_game_start)
        if start <= now <= end:
            return week

    upcoming = [
        week for week in calendar if timeutils.parse_utc(week.first_game_start) > now
    ]
    if not upcoming:
        return None
    return min(upcoming, key=lambda week: timeutils.parse_utc(week.first_game_start))
