from datetime import datetime, timedelta, timezone

import pytest

from bot.commands import status_panel
from bot.config import settings
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


# --- cleanup_channel ---


class FakeCleanupMessage:
    def __init__(self, message_id, created_at):
        self.id = message_id
        self.created_at = created_at
        self.deleted = False

    async def delete(self):
        self.deleted = True


class FakeCleanupChannel:
    def __init__(self, messages):
        self.messages = messages  # newest-first, like real history()

    async def history(self, limit=200):
        for m in self.messages[:limit]:
            yield m


class FakeCleanupBot:
    def __init__(self, channel):
        self._channel = channel

    def get_channel(self, channel_id):
        return self._channel

    async def fetch_channel(self, channel_id):
        return self._channel


@pytest.fixture
def panel_channel_configured(monkeypatch):
    monkeypatch.setattr(settings, "admin_log_channel_id", 555)


async def test_cleanup_channel_noop_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "admin_log_channel_id", None)
    channel = FakeCleanupChannel([])
    removed = await status_panel.cleanup_channel(FakeCleanupBot(channel))
    assert removed == 0


async def test_cleanup_channel_deletes_only_messages_older_than_cutoff(panel_channel_configured):
    now = datetime.now(timezone.utc)
    old_message = FakeCleanupMessage(1, now - timedelta(minutes=10))
    fresh_message = FakeCleanupMessage(2, now - timedelta(minutes=1))
    channel = FakeCleanupChannel([fresh_message, old_message])

    removed = await status_panel.cleanup_channel(FakeCleanupBot(channel))

    assert removed == 1
    assert old_message.deleted is True
    assert fresh_message.deleted is False


async def test_cleanup_channel_never_deletes_the_current_panel_even_if_old(panel_channel_configured):
    now = datetime.now(timezone.utc)
    panel_message = FakeCleanupMessage(1, now - timedelta(minutes=30))
    other_old_message = FakeCleanupMessage(2, now - timedelta(minutes=10))
    channel = FakeCleanupChannel([other_old_message, panel_message])
    status_panel._panels[555] = panel_message

    try:
        removed = await status_panel.cleanup_channel(FakeCleanupBot(channel))
        assert removed == 1
        assert panel_message.deleted is False
        assert other_old_message.deleted is True
    finally:
        status_panel._panels.pop(555, None)
