from dataclasses import dataclass

import httpx

BASE_URL = "https://api.the-odds-api.com"
SPORT_KEY = "americanfootball_ncaaf"
MARKETS = "spreads,totals,h2h"
REGIONS = "us"
CREDITS_PER_FETCH = 3  # markets(3) x regions(1), per The Odds API's cost model


@dataclass
class OddsEvent:
    home_team_raw: str
    away_team_raw: str
    commence_time: str
    book: str
    spread_home: float | None = None
    spread_price_home: int | None = None
    spread_price_away: int | None = None
    moneyline_home: int | None = None
    moneyline_away: int | None = None
    total_points: float | None = None
    over_price: int | None = None
    under_price: int | None = None


def _find_market(markets: list[dict], key: str) -> dict | None:
    for market in markets:
        if market["key"] == key:
            return market
    return None


def _find_outcome(outcomes: list[dict], name: str) -> dict | None:
    for outcome in outcomes:
        if outcome["name"] == name:
            return outcome
    return None


def _parse_event(raw: dict) -> OddsEvent | None:
    bookmakers = raw.get("bookmakers") or []
    if not bookmakers:
        return None

    bookmaker = bookmakers[0]
    markets = bookmaker.get("markets", [])
    home_team = raw["home_team"]
    away_team = raw["away_team"]
    event = OddsEvent(
        home_team_raw=home_team,
        away_team_raw=away_team,
        commence_time=raw["commence_time"],
        book=bookmaker["key"],
    )

    spreads = _find_market(markets, "spreads")
    if spreads:
        home_outcome = _find_outcome(spreads["outcomes"], home_team)
        away_outcome = _find_outcome(spreads["outcomes"], away_team)
        if home_outcome:
            event.spread_home = home_outcome.get("point")
            event.spread_price_home = home_outcome.get("price")
        if away_outcome:
            event.spread_price_away = away_outcome.get("price")

    h2h = _find_market(markets, "h2h")
    if h2h:
        home_outcome = _find_outcome(h2h["outcomes"], home_team)
        away_outcome = _find_outcome(h2h["outcomes"], away_team)
        if home_outcome:
            event.moneyline_home = home_outcome.get("price")
        if away_outcome:
            event.moneyline_away = away_outcome.get("price")

    totals = _find_market(markets, "totals")
    if totals:
        over_outcome = _find_outcome(totals["outcomes"], "Over")
        under_outcome = _find_outcome(totals["outcomes"], "Under")
        if over_outcome:
            event.total_points = over_outcome.get("point")
            event.over_price = over_outcome.get("price")
        if under_outcome:
            event.under_price = under_outcome.get("price")

    return event


class OddsClient:
    def __init__(self, api_key: str, log_usage=None):
        self._api_key = api_key
        self._log_usage = log_usage

    async def get_ncaaf_odds(self) -> list[OddsEvent]:
        async with httpx.AsyncClient(base_url=BASE_URL) as client:
            response = await client.get(
                f"/v4/sports/{SPORT_KEY}/odds",
                params={
                    "apiKey": self._api_key,
                    "regions": REGIONS,
                    "markets": MARKETS,
                    "oddsFormat": "american",
                },
            )
            response.raise_for_status()
            if self._log_usage:
                self._log_usage("odds_api", f"/v4/sports/{SPORT_KEY}/odds", CREDITS_PER_FETCH)
            events = [_parse_event(raw) for raw in response.json()]
            return [event for event in events if event is not None]
