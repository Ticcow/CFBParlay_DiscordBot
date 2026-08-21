from dataclasses import dataclass

import httpx

BASE_URL = "https://api.collegefootballdata.com"


@dataclass
class CfbdGame:
    cfbd_game_id: int
    home_team: str
    away_team: str
    start_time_utc: str
    status: str
    home_score: int | None
    away_score: int | None


def _parse_game(raw: dict) -> CfbdGame:
    completed = bool(raw.get("completed"))
    return CfbdGame(
        cfbd_game_id=raw["id"],
        home_team=raw["homeTeam"],
        away_team=raw["awayTeam"],
        start_time_utc=raw["startDate"],
        status="final" if completed else "scheduled",
        home_score=raw.get("homePoints"),
        away_score=raw.get("awayPoints"),
    )


@dataclass
class CalendarWeek:
    season: int
    week: int
    season_type: str
    first_game_start: str
    last_game_start: str


def _parse_calendar_week(raw: dict) -> CalendarWeek:
    return CalendarWeek(
        season=raw["season"],
        week=raw["week"],
        season_type=raw["seasonType"],
        first_game_start=raw["firstGameStart"],
        last_game_start=raw["lastGameStart"],
    )


@dataclass
class RankedTeam:
    rank: int
    school: str


@dataclass
class TeamInfo:
    school: str
    logo_url: str | None
    color: str | None = None
    conference: str | None = None


def _parse_teams_top25(raw_weeks: list[dict]) -> list[RankedTeam]:
    for week_entry in raw_weeks:
        for poll in week_entry.get("polls", []):
            if poll.get("poll") == "AP Top 25":
                return [
                    RankedTeam(rank=r["rank"], school=r["school"]) for r in poll["ranks"]
                ]
    return []


def _parse_team(raw: dict) -> TeamInfo:
    logos = raw.get("logos") or []
    return TeamInfo(
        school=raw["school"],
        logo_url=logos[0] if logos else None,
        color=raw.get("color"),
        conference=raw.get("conference"),
    )


class CfbdClient:
    def __init__(self, api_key: str, log_usage=None):
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._log_usage = log_usage

    async def get_games(
        self, year: int, week: int, season_type: str = "regular"
    ) -> list[CfbdGame]:
        async with httpx.AsyncClient(base_url=BASE_URL, headers=self._headers) as client:
            response = await client.get(
                "/games",
                params={
                    "year": year,
                    "week": week,
                    "seasonType": season_type,
                    "division": "fbs",
                },
            )
            response.raise_for_status()
            if self._log_usage:
                self._log_usage("cfbd", "/games")
            return [_parse_game(raw) for raw in response.json()]

    async def get_calendar(self, year: int) -> list[CalendarWeek]:
        async with httpx.AsyncClient(base_url=BASE_URL, headers=self._headers) as client:
            response = await client.get("/calendar", params={"year": year})
            response.raise_for_status()
            if self._log_usage:
                self._log_usage("cfbd", "/calendar")
            return [_parse_calendar_week(raw) for raw in response.json()]

    async def get_ap_top25(
        self, year: int, week: int, season_type: str = "regular"
    ) -> list[RankedTeam]:
        async with httpx.AsyncClient(base_url=BASE_URL, headers=self._headers) as client:
            response = await client.get(
                "/rankings", params={"year": year, "week": week, "seasonType": season_type}
            )
            response.raise_for_status()
            if self._log_usage:
                self._log_usage("cfbd", "/rankings")
            return _parse_teams_top25(response.json())

    async def get_teams(self, year: int) -> list[TeamInfo]:
        async with httpx.AsyncClient(base_url=BASE_URL, headers=self._headers) as client:
            response = await client.get("/teams/fbs", params={"year": year})
            response.raise_for_status()
            if self._log_usage:
                self._log_usage("cfbd", "/teams/fbs")
            return [_parse_team(raw) for raw in response.json()]
