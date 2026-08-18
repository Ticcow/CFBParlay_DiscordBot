import respx
from httpx import Response

from bot.integrations.odds_client import OddsClient

RAW_EVENT = {
    "id": "abc123",
    "commence_time": "2026-08-29T19:00:00Z",
    "home_team": "Texas Longhorns",
    "away_team": "Ohio State Buckeyes",
    "bookmakers": [
        {
            "key": "draftkings",
            "markets": [
                {
                    "key": "spreads",
                    "outcomes": [
                        {"name": "Texas Longhorns", "price": -110, "point": -6.5},
                        {"name": "Ohio State Buckeyes", "price": -110, "point": 6.5},
                    ],
                },
                {
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Texas Longhorns", "price": -250},
                        {"name": "Ohio State Buckeyes", "price": 200},
                    ],
                },
                {
                    "key": "totals",
                    "outcomes": [
                        {"name": "Over", "price": -110, "point": 54.5},
                        {"name": "Under", "price": -110, "point": 54.5},
                    ],
                },
            ],
        }
    ],
}


@respx.mock
async def test_get_ncaaf_odds_parses_all_markets():
    respx.get(
        "https://api.the-odds-api.com/v4/sports/americanfootball_ncaaf/odds"
    ).mock(return_value=Response(200, json=[RAW_EVENT]))

    client = OddsClient(api_key="test-key")
    events = await client.get_ncaaf_odds()

    assert len(events) == 1
    event = events[0]
    assert event.home_team_raw == "Texas Longhorns"
    assert event.away_team_raw == "Ohio State Buckeyes"
    assert event.book == "draftkings"
    assert event.spread_home == -6.5
    assert event.spread_price_home == -110
    assert event.spread_price_away == -110
    assert event.moneyline_home == -250
    assert event.moneyline_away == 200
    assert event.total_points == 54.5
    assert event.over_price == -110
    assert event.under_price == -110


@respx.mock
async def test_get_ncaaf_odds_skips_events_with_no_bookmakers():
    event_without_odds = {**RAW_EVENT, "bookmakers": []}
    respx.get(
        "https://api.the-odds-api.com/v4/sports/americanfootball_ncaaf/odds"
    ).mock(return_value=Response(200, json=[event_without_odds]))

    client = OddsClient(api_key="test-key")
    events = await client.get_ncaaf_odds()

    assert events == []


@respx.mock
async def test_get_ncaaf_odds_logs_usage_with_3_credits():
    respx.get(
        "https://api.the-odds-api.com/v4/sports/americanfootball_ncaaf/odds"
    ).mock(return_value=Response(200, json=[RAW_EVENT]))
    calls = []

    client = OddsClient(
        api_key="test-key",
        log_usage=lambda service, endpoint, credits: calls.append((service, endpoint, credits)),
    )
    await client.get_ncaaf_odds()

    assert calls == [("odds_api", "/v4/sports/americanfootball_ncaaf/odds", 3)]
