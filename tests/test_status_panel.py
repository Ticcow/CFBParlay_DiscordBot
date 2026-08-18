from datetime import timedelta

from bot.commands import status_panel
from bot.integrations.cfbd_client import CfbdGame
from bot.integrations.odds_client import OddsEvent
from bot.parlays import payout, repository, timeutils


class FakeBot:
    def __init__(self, conn):
        self.conn = conn


def test_build_embed_with_no_week(conn):
    embed = status_panel._build_embed(FakeBot(conn), None)
    assert embed.description == "No week is open yet."


def test_build_embed_with_no_participants(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    week = repository.get_week(conn, week_id)

    embed = status_panel._build_embed(FakeBot(conn), week)

    standings_field = next(f for f in embed.fields if f.name == "Standings")
    assert "Nobody has opted in" in standings_field.value


def test_build_embed_with_participants_and_no_bets(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.opt_in(conn, user_id=1, week_id=week_id)
    week = repository.get_week(conn, week_id)

    embed = status_panel._build_embed(FakeBot(conn), week)

    standings_field = next(f for f in embed.fields if "Standings" in f.name)
    assert "1000.00" in standings_field.value
    bets_field = next(f for f in embed.fields if f.name == "Bets")
    assert "No parlays submitted yet." in bets_field.value


def _seed_submitted_parlay(conn, start_offset_hours):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    now = timeutils.utc_now()
    start = (now + timedelta(hours=start_offset_hours)).isoformat()
    repository.upsert_games(conn, week_id, [CfbdGame(1, "Texas", "Ohio State", start, "scheduled", None, None)])
    game, _ = repository.find_game_by_teams(conn, week_id, "Texas", "Ohio State")
    event = OddsEvent("Texas", "Ohio State", start, "draftkings", moneyline_home=-150, moneyline_away=130)
    repository.insert_odds_snapshot(conn, game["id"], event, flipped=False)
    snapshot = repository.get_latest_odds_snapshot(conn, game["id"])

    participant = repository.opt_in(conn, user_id=1, week_id=week_id)
    parlay_id = repository.start_parlay(conn, 1, week_id)
    repository.add_leg(conn, parlay_id, game["id"], snapshot["id"], "moneyline", "home", None, -150)
    potential = payout.potential_payout(100, [-150])
    repository.submit_parlay(conn, parlay_id, participant["id"], 100.0, potential)
    return week_id


def test_build_embed_hides_bet_details_before_kickoff(conn):
    week_id = _seed_submitted_parlay(conn, start_offset_hours=5)  # game hasn't started
    week = repository.get_week(conn, week_id)

    embed = status_panel._build_embed(FakeBot(conn), week)

    bets_field = next(f for f in embed.fields if f.name == "Bets")
    assert "hidden until the first game kicks off" in bets_field.value
    assert "Texas" not in bets_field.value


def test_build_embed_shows_bet_details_after_kickoff(conn):
    week_id = _seed_submitted_parlay(conn, start_offset_hours=-1)  # game already started
    week = repository.get_week(conn, week_id)

    embed = status_panel._build_embed(FakeBot(conn), week)

    bet_fields = [f for f in embed.fields if "Texas" in f.value or "Texas" in f.name]
    assert bet_fields, "expected a field showing the actual leg details once visible"
