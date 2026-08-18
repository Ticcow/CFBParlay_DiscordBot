import respx
from httpx import Response

from bot.integrations.cfbd_client import CfbdClient

RAW_GAME = {
    "id": 12345,
    "homeTeam": "Texas",
    "awayTeam": "Ohio State",
    "startDate": "2026-08-29T19:00:00.000Z",
    "completed": False,
    "homePoints": None,
    "awayPoints": None,
}


@respx.mock
async def test_get_games_parses_response():
    respx.get("https://api.collegefootballdata.com/games").mock(
        return_value=Response(200, json=[RAW_GAME])
    )

    client = CfbdClient(api_key="test-key")
    games = await client.get_games(2026, 1)

    assert len(games) == 1
    game = games[0]
    assert game.cfbd_game_id == 12345
    assert game.home_team == "Texas"
    assert game.away_team == "Ohio State"
    assert game.status == "scheduled"
    assert game.home_score is None


@respx.mock
async def test_get_games_marks_completed_game_final():
    completed_game = {**RAW_GAME, "completed": True, "homePoints": 24, "awayPoints": 17}
    respx.get("https://api.collegefootballdata.com/games").mock(
        return_value=Response(200, json=[completed_game])
    )

    client = CfbdClient(api_key="test-key")
    games = await client.get_games(2026, 1)

    assert games[0].status == "final"
    assert games[0].home_score == 24
    assert games[0].away_score == 17


@respx.mock
async def test_get_games_invokes_usage_logger():
    respx.get("https://api.collegefootballdata.com/games").mock(
        return_value=Response(200, json=[RAW_GAME])
    )
    calls = []

    client = CfbdClient(api_key="test-key", log_usage=lambda service, endpoint: calls.append((service, endpoint)))
    await client.get_games(2026, 1)

    assert calls == [("cfbd", "/games")]
