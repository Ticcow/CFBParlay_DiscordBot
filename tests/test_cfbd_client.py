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
    "homeClassification": "fbs",
    "awayClassification": "fbs",
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


@respx.mock
async def test_get_games_filters_out_matchups_with_no_fbs_team_at_all():
    # CFBD's "division" query param doesn't actually filter server-side - it
    # returns every classification regardless, so get_games has to drop
    # anything that doesn't involve at least one FBS team itself.
    fcs_vs_d2_game = {
        **RAW_GAME,
        "id": 99999,
        "homeTeam": "Morehead State",
        "awayTeam": "Ohio Dominican",
        "homeClassification": "fcs",
        "awayClassification": "ii",
    }
    respx.get("https://api.collegefootballdata.com/games").mock(
        return_value=Response(200, json=[RAW_GAME, fcs_vs_d2_game])
    )

    client = CfbdClient(api_key="test-key")
    games = await client.get_games(2026, 1)

    assert [g.cfbd_game_id for g in games] == [12345]


@respx.mock
async def test_get_games_keeps_a_cupcake_game_with_only_one_fbs_side():
    # a Week 1 FBS-vs-FCS game still has real sportsbook lines, so it's worth
    # tracking even though the opponent isn't FBS
    cupcake_game = {
        **RAW_GAME,
        "id": 88888,
        "homeTeam": "Alabama",
        "awayTeam": "Some FCS School",
        "homeClassification": "fbs",
        "awayClassification": "fcs",
    }
    respx.get("https://api.collegefootballdata.com/games").mock(
        return_value=Response(200, json=[cupcake_game])
    )

    client = CfbdClient(api_key="test-key")
    games = await client.get_games(2026, 1)

    assert [g.cfbd_game_id for g in games] == [88888]


RAW_RANKINGS_WEEK = {
    "season": 2026,
    "week": 1,
    "seasonType": "regular",
    "polls": [
        {
            "poll": "Coaches Poll",
            "ranks": [{"rank": 1, "school": "Wrong Poll Team"}],
        },
        {
            "poll": "AP Top 25",
            "ranks": [
                {"rank": 1, "school": "Georgia"},
                {"rank": 2, "school": "Ohio State"},
            ],
        },
    ],
}


@respx.mock
async def test_get_ap_top25_finds_the_ap_poll_specifically():
    respx.get("https://api.collegefootballdata.com/rankings").mock(
        return_value=Response(200, json=[RAW_RANKINGS_WEEK])
    )

    client = CfbdClient(api_key="test-key")
    ranked = await client.get_ap_top25(2026, 1)

    assert [(r.rank, r.school) for r in ranked] == [(1, "Georgia"), (2, "Ohio State")]


@respx.mock
async def test_get_ap_top25_returns_empty_when_no_ap_poll_present():
    week_with_no_ap_poll = {**RAW_RANKINGS_WEEK, "polls": [RAW_RANKINGS_WEEK["polls"][0]]}
    respx.get("https://api.collegefootballdata.com/rankings").mock(
        return_value=Response(200, json=[week_with_no_ap_poll])
    )

    client = CfbdClient(api_key="test-key")
    ranked = await client.get_ap_top25(2026, 1)

    assert ranked == []


@respx.mock
async def test_get_teams_parses_logo_from_first_url():
    respx.get("https://api.collegefootballdata.com/teams/fbs").mock(
        return_value=Response(200, json=[
            {"school": "Notre Dame", "logos": ["https://example.com/nd1.png", "https://example.com/nd2.png"]},
            {"school": "Army", "logos": []},
        ])
    )

    client = CfbdClient(api_key="test-key")
    teams = await client.get_teams(2026)

    assert teams[0].school == "Notre Dame"
    assert teams[0].logo_url == "https://example.com/nd1.png"
    assert teams[1].logo_url is None
