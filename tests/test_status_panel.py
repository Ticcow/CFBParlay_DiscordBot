from datetime import datetime, timedelta, timezone

import pytest

from bot.commands import status_panel
from bot.config import settings
from bot.integrations.cfbd_client import CfbdGame
from bot.integrations.odds_client import OddsEvent
from bot.parlays import grading, payout, repository, timeutils


class FakeUser:
    def __init__(self, user_id):
        self.id = user_id
        self.name = f"user{user_id}"


class FakeBot:
    def __init__(self, conn):
        self.conn = conn

    def get_user(self, user_id):
        return None  # force resolve_username through the fetch path below

    async def fetch_user(self, user_id):
        return FakeUser(user_id)


async def test_build_embed_with_no_week(conn):
    embed = await status_panel._build_embed(FakeBot(conn), None)
    assert embed.description == "No week is open yet."


async def test_build_embed_always_shows_how_to_play(conn):
    embed_no_week = await status_panel._build_embed(FakeBot(conn), None)
    how_to_play_no_week = next(f for f in embed_no_week.fields if f.name == "How to Play")
    assert "Opt In" in how_to_play_no_week.value
    assert "Start Parlay" in how_to_play_no_week.value

    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    week = repository.get_week(conn, week_id)
    embed_with_week = await status_panel._build_embed(FakeBot(conn), week)
    how_to_play_with_week = next(f for f in embed_with_week.fields if f.name == "How to Play")
    assert how_to_play_with_week.value == how_to_play_no_week.value


async def test_build_embed_with_no_participants(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    week = repository.get_week(conn, week_id)

    embed = await status_panel._build_embed(FakeBot(conn), week)

    standings_field = next(f for f in embed.fields if f.name == "Standings")
    assert "Nobody has opted in" in standings_field.value


async def test_build_embed_with_participants_and_no_bets(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.opt_in(conn, user_id=1, week_id=week_id)
    week = repository.get_week(conn, week_id)

    embed = await status_panel._build_embed(FakeBot(conn), week)

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


async def test_build_embed_shows_bet_details_even_before_kickoff(conn):
    week_id = _seed_submitted_parlay(conn, start_offset_hours=5)  # game hasn't started yet
    week = repository.get_week(conn, week_id)

    embed = await status_panel._build_embed(FakeBot(conn), week)

    bet_fields = [f for f in embed.fields if f.name.startswith("user1 —")]
    assert bet_fields, "bets should be visible immediately, not hidden until kickoff"
    assert "1. ⏳" in bet_fields[0].value


async def test_build_embed_shows_potential_payout_before_grading(conn):
    week_id = _seed_submitted_parlay(conn, start_offset_hours=5)
    week = repository.get_week(conn, week_id)

    embed = await status_panel._build_embed(FakeBot(conn), week)

    bet_field = next(f for f in embed.fields if f.name.startswith("user1 —"))
    assert "potential" in bet_field.name
    assert "[submitted]" in bet_field.value


async def test_build_embed_shows_actual_payout_and_result_once_graded(conn):
    week_id = _seed_submitted_parlay(conn, start_offset_hours=-1)  # game already started
    week = repository.get_week(conn, week_id)
    game, _ = repository.find_game_by_teams(conn, week_id, "Texas", "Ohio State")
    repository.set_game_final_score(conn, game["id"], home_score=24, away_score=17)  # Texas (home) wins
    grading.grade_week(conn, week_id)

    embed = await status_panel._build_embed(FakeBot(conn), week)

    bet_field = next(f for f in embed.fields if f.name.startswith("user1 —"))
    assert "payout" in bet_field.name
    assert "potential" not in bet_field.name
    assert "[WIN]" in bet_field.value


async def test_build_embed_groups_multiple_parlays_under_one_field_per_user(conn):
    # a noisy panel with one field per parlay was hard to read once someone
    # had several parlays going - group by bettor instead, one line per parlay
    week_id = _seed_submitted_parlay(conn, start_offset_hours=5)
    week = repository.get_week(conn, week_id)
    game, _ = repository.find_game_by_teams(conn, week_id, "Texas", "Ohio State")
    snapshot = repository.get_latest_odds_snapshot(conn, game["id"])
    participant = repository.get_participant(conn, 1, week_id)
    second_parlay_id = repository.start_parlay(conn, 1, week_id)
    repository.add_leg(conn, second_parlay_id, game["id"], snapshot["id"], "moneyline", "home", None, -150)
    repository.submit_parlay(conn, second_parlay_id, participant["id"], 50.0, 83.33)

    embed = await status_panel._build_embed(FakeBot(conn), week)

    user_bet_fields = [f for f in embed.fields if f.name.startswith("user1 —")]
    assert len(user_bet_fields) == 1
    assert "2 parlays" in user_bet_fields[0].name
    assert "1. ⏳" in user_bet_fields[0].value
    assert "2. ⏳" in user_bet_fields[0].value


async def test_build_embed_bets_field_name_uses_plain_username_not_a_mention(conn):
    # embed field *names* don't resolve <@id> mentions the way field values
    # and message content do - Discord just shows the literal raw text - so
    # the Bets field name must carry the already-resolved plain username
    week_id = _seed_submitted_parlay(conn, start_offset_hours=5)
    week = repository.get_week(conn, week_id)

    embed = await status_panel._build_embed(FakeBot(conn), week)

    bet_field = next(f for f in embed.fields if f.name.startswith("user1 —"))
    assert "<@" not in bet_field.name


# --- cleanup_channel ---


class FakeCleanupUser:
    def __init__(self, user_id):
        self.id = user_id


class FakeCleanupEmbed:
    def __init__(self, title):
        self.title = title


BOT_USER = FakeCleanupUser("bot")
HUMAN_USER = FakeCleanupUser("human")


def _panel_embed():
    return FakeCleanupEmbed(status_panel.PANEL_EMBED_TITLE)


class FakeCleanupMessage:
    def __init__(self, message_id, created_at, author=BOT_USER, embeds=None):
        self.id = message_id
        self.created_at = created_at
        self.author = author
        self.embeds = embeds or []
        self.deleted = False

    async def delete(self):
        self.deleted = True


class FakeCleanupGuild:
    def __init__(self, me):
        self.me = me


class FakeCleanupChannel:
    def __init__(self, messages, guild=None):
        self.messages = messages  # newest-first, like real history()
        self.guild = guild if guild is not None else FakeCleanupGuild(me=BOT_USER)

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


async def test_cleanup_channel_deletes_only_stale_panel_reposts_older_than_cutoff(panel_channel_configured):
    now = datetime.now(timezone.utc)
    old_panel = FakeCleanupMessage(1, now - timedelta(minutes=10), embeds=[_panel_embed()])
    fresh_panel = FakeCleanupMessage(2, now - timedelta(minutes=1), embeds=[_panel_embed()])
    channel = FakeCleanupChannel([fresh_panel, old_panel])

    removed = await status_panel.cleanup_channel(FakeCleanupBot(channel))

    assert removed == 1
    assert old_panel.deleted is True
    assert fresh_panel.deleted is False


async def test_cleanup_channel_never_deletes_the_current_panel_even_if_old(panel_channel_configured):
    now = datetime.now(timezone.utc)
    panel_message = FakeCleanupMessage(1, now - timedelta(minutes=30), embeds=[_panel_embed()])
    other_old_panel = FakeCleanupMessage(2, now - timedelta(minutes=10), embeds=[_panel_embed()])
    channel = FakeCleanupChannel([other_old_panel, panel_message])
    status_panel._panels[555] = panel_message

    try:
        removed = await status_panel.cleanup_channel(FakeCleanupBot(channel))
        assert removed == 1
        assert panel_message.deleted is False
        assert other_old_panel.deleted is True
    finally:
        status_panel._panels.pop(555, None)


async def test_cleanup_channel_never_deletes_user_chat_even_if_old(panel_channel_configured):
    now = datetime.now(timezone.utc)
    banter = FakeCleanupMessage(1, now - timedelta(minutes=30), author=HUMAN_USER)
    channel = FakeCleanupChannel([banter])

    removed = await status_panel.cleanup_channel(FakeCleanupBot(channel))

    assert removed == 0
    assert banter.deleted is False


async def test_cleanup_channel_never_deletes_the_bots_own_zingers_and_announcements(
    panel_channel_configured,
):
    now = datetime.now(timezone.utc)
    knockout_zinger = FakeCleanupMessage(1, now - timedelta(minutes=30))  # plain text, no embed
    weekly_recap = FakeCleanupMessage(
        2, now - timedelta(minutes=30), embeds=[FakeCleanupEmbed("Some other embed")]
    )
    channel = FakeCleanupChannel([knockout_zinger, weekly_recap])

    removed = await status_panel.cleanup_channel(FakeCleanupBot(channel))

    assert removed == 0
    assert knockout_zinger.deleted is False
    assert weekly_recap.deleted is False
