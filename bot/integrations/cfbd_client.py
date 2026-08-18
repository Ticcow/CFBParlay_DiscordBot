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
