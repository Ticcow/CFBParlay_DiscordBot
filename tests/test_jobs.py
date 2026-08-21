from datetime import datetime, timezone

import pytest

from bot.integrations.cfbd_client import CalendarWeek, CfbdGame, RankedTeam
from bot.integrations.odds_client import OddsEvent
from bot.parlays import repository, timeutils
from bot.scheduler import jobs

FIXED_NOW = datetime(2026, 8, 28, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    monkeypatch.setattr(timeutils, "utc_now", lambda: FIXED_NOW)


class FakeCfbdClient:
    def __init__(self):
        self.calendar = []
        self.games = []
        self.ranked_teams = []

    async def get_calendar(self, year):
        return self.calendar

    async def get_games(self, year, week, season_type):
        return self.games

    async def get_ap_top25(self, year, week, season_type):
        return self.ranked_teams


class FakeOddsClient:
    def __init__(self):
        self.events = []

    async def get_ncaaf_odds(self):
        return self.events


class FakeUser:
    def __init__(self, user_id):
        self.id = user_id
        self.sent = []

    async def send(self, message):
        self.sent.append(message)


class FakeBot:
    def __init__(self, conn):
        self.conn = conn
        self.cfbd = FakeCfbdClient()
        self.odds = FakeOddsClient()
        self.announcements = []
        self._users = {}

    async def announce(self, message):
        self.announcements.append(message)

    async def fetch_user(self, user_id):
        return self._users.setdefault(user_id, FakeUser(user_id))


def make_calendar_week():
    return CalendarWeek(
        season=2026, week=1, season_type="regular",
        first_game_start="2026-08-25T00:00:00Z", last_game_start="2026-08-31T23:59:00Z",
    )


async def test_sync_week_games_creates_week_and_announces_once(conn):
    bot = FakeBot(conn)
    bot.cfbd.calendar = [make_calendar_week()]
    bot.cfbd.games = [CfbdGame(1, "Texas", "Ohio State", "2026-08-29T19:00:00Z", "scheduled", None, None)]
    bot.cfbd.ranked_teams = [RankedTeam(1, "Texas")]

    week_id = await jobs.sync_week_games(bot)

    assert week_id is not None
    assert len(bot.announcements) == 1
    assert "Week 1" in bot.announcements[0]
    assert repository.get_latest_week(conn)["week_number"] == 1
    rankings = conn.execute("SELECT school FROM rankings WHERE week_id = ?", (week_id,)).fetchall()
    assert [r["school"] for r in rankings] == ["Texas"]

    week_id_again = await jobs.sync_week_games(bot)  # re-syncing shouldn't re-announce
    assert week_id_again == week_id
    assert len(bot.announcements) == 1


async def test_sync_week_games_returns_none_when_calendar_has_no_match(conn):
    bot = FakeBot(conn)  # empty calendar - off-season
    result = await jobs.sync_week_games(bot)
    assert result is None
    assert bot.announcements == []
    assert repository.get_latest_week(conn) is None


async def test_fetch_odds_noop_without_a_synced_week(conn):
    bot = FakeBot(conn)
    await jobs.fetch_odds(bot)  # should not raise


async def test_fetch_odds_syncs_events_for_latest_week(conn):
    bot = FakeBot(conn)
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.upsert_games(
        conn, week_id, [CfbdGame(1, "Texas", "Ohio State", "2026-08-29T19:00:00Z", "scheduled", None, None)]
    )
    bot.odds.events = [
        OddsEvent("Texas", "Ohio State", "2026-08-29T19:00:00Z", "draftkings", moneyline_home=-150, moneyline_away=130)
    ]

    await jobs.fetch_odds(bot)

    game, _ = repository.find_game_by_teams(conn, week_id, "Texas", "Ohio State")
    assert repository.get_latest_odds_snapshot(conn, game["id"]) is not None


async def test_lock_check_job_dms_owner_of_expired_draft(conn):
    bot = FakeBot(conn)
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.upsert_games(
        conn, week_id, [CfbdGame(1, "Texas", "Ohio State", "2020-01-01T19:00:00Z", "scheduled", None, None)]
    )
    game, _ = repository.find_game_by_teams(conn, week_id, "Texas", "Ohio State")
    event = OddsEvent("Texas", "Ohio State", game["start_time_utc"], "draftkings", moneyline_home=-150, moneyline_away=130)
    repository.insert_odds_snapshot(conn, game["id"], event, flipped=False)
    snapshot = repository.get_latest_odds_snapshot(conn, game["id"])

    parlay_id = repository.start_parlay(conn, user_id=42, week_id=week_id)
    repository.add_leg(conn, parlay_id, game["id"], snapshot["id"], "moneyline", "home", None, -150)

    result = await jobs.lock_check_job(bot)

    assert result["expired_drafts"] == [(42, parlay_id)]
    assert len(bot._users[42].sent) == 1


async def test_poll_scores_triggers_grading_once_week_is_all_final(conn):
    bot = FakeBot(conn)
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.upsert_games(
        conn, week_id, [CfbdGame(1, "Texas", "Ohio State", "2026-08-29T19:00:00Z", "scheduled", None, None)]
    )
    bot.cfbd.games = [CfbdGame(1, "Texas", "Ohio State", "2026-08-29T19:00:00Z", "final", 24, 17)]

    await jobs.poll_scores(bot)

    assert repository.list_games(conn, week_id)[0]["status"] == "final"
    # grade_week_job ran as a side effect; nobody opted in, so finalize_week has
    # nothing to mark and posts no announcement - it just shouldn't raise
    assert bot.announcements == []


async def test_poll_scores_grades_a_finished_leg_without_finishing_the_whole_week(conn):
    bot = FakeBot(conn)
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.upsert_games(
        conn,
        week_id,
        [
            CfbdGame(1, "Texas", "Ohio State", "2026-08-29T19:00:00Z", "scheduled", None, None),
            CfbdGame(2, "Alabama", "Georgia", "2026-08-29T19:00:00Z", "scheduled", None, None),
        ],
    )
    texas_game, _ = repository.find_game_by_teams(conn, week_id, "Texas", "Ohio State")
    bama_game, _ = repository.find_game_by_teams(conn, week_id, "Alabama", "Georgia")
    for game in (texas_game, bama_game):
        event = OddsEvent(
            game["home_team"], game["away_team"], game["start_time_utc"], "draftkings",
            moneyline_home=-150, moneyline_away=130,
        )
        repository.insert_odds_snapshot(conn, game["id"], event, flipped=False)

    participant = repository.opt_in(conn, user_id=42, week_id=week_id)
    parlay_id = repository.start_parlay(conn, 42, week_id)
    texas_snapshot = repository.get_latest_odds_snapshot(conn, texas_game["id"])
    bama_snapshot = repository.get_latest_odds_snapshot(conn, bama_game["id"])
    repository.add_leg(conn, parlay_id, texas_game["id"], texas_snapshot["id"], "moneyline", "home", None, -150)
    repository.add_leg(conn, parlay_id, bama_game["id"], bama_snapshot["id"], "moneyline", "home", None, -150)
    repository.submit_parlay(conn, parlay_id, participant["id"], 100.0, 277.78)

    # only Texas has finished so far; Alabama is still to be played
    bot.cfbd.games = [
        CfbdGame(1, "Texas", "Ohio State", "2026-08-29T19:00:00Z", "final", 24, 17),
        CfbdGame(2, "Alabama", "Georgia", "2026-08-29T19:00:00Z", "scheduled", None, None),
    ]

    await jobs.poll_scores(bot)

    legs = repository.list_legs_with_games(conn, parlay_id)
    results_by_game = {leg["game_id"]: leg["result"] for leg in legs}
    assert results_by_game[texas_game["id"]] == "win"
    assert results_by_game[bama_game["id"]] == "pending"
    # the parlay itself isn't graded yet - Alabama hasn't finished
    assert repository.get_parlay(conn, parlay_id)["status"] == "submitted"


async def test_api_usage_report_job_noop_with_no_usage(conn):
    bot = FakeBot(conn)
    await jobs.api_usage_report_job(bot)
    assert bot.announcements == []


async def test_api_usage_report_job_summarizes_usage(conn):
    bot = FakeBot(conn)
    repository.log_api_usage(conn, "cfbd", "/games", 1)
    repository.log_api_usage(conn, "odds_api", "/v4/sports/x/odds", 3)

    await jobs.api_usage_report_job(bot)

    assert len(bot.announcements) == 1
    assert "cfbd" in bot.announcements[0]
    assert "odds_api" in bot.announcements[0]


async def test_guarded_job_posts_failure_alert_instead_of_raising(conn):
    bot = FakeBot(conn)

    async def failing_job(_bot):
        raise RuntimeError("boom")

    await jobs._guarded(bot, "failing_job", failing_job)()

    assert len(bot.announcements) == 1
    assert "failing_job" in bot.announcements[0]


def _setup_week_kicking_off_in(conn, hours_from_now):
    from datetime import timedelta

    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    kickoff = (FIXED_NOW + timedelta(hours=hours_from_now)).isoformat().replace("+00:00", "Z")
    repository.upsert_games(
        conn, week_id, [CfbdGame(1, "Texas", "Ohio State", kickoff, "scheduled", None, None)]
    )
    return week_id


async def test_pregame_reminder_noop_with_no_week(conn):
    bot = FakeBot(conn)
    await jobs.pregame_reminder_job(bot)
    assert bot.announcements == []


async def test_pregame_reminder_noop_before_any_threshold(conn):
    bot = FakeBot(conn)
    week_id = _setup_week_kicking_off_in(conn, hours_from_now=48)
    repository.opt_in(conn, user_id=1, week_id=week_id)

    await jobs.pregame_reminder_job(bot)

    assert bot.announcements == []
    assert repository.has_sent_reminder(conn, week_id, 24) is False


async def test_pregame_reminder_mentions_only_users_with_balance(conn):
    bot = FakeBot(conn)
    week_id = _setup_week_kicking_off_in(conn, hours_from_now=20)
    repository.opt_in(conn, user_id=1, week_id=week_id)
    repository.opt_in(conn, user_id=2, week_id=week_id)
    conn.execute(
        "UPDATE week_participants SET current_balance = 0 WHERE user_id = 2 AND week_id = ?",
        (week_id,),
    )
    conn.commit()

    await jobs.pregame_reminder_job(bot)

    assert len(bot.announcements) == 1
    assert "<@1>" in bot.announcements[0]
    assert "<@2>" not in bot.announcements[0]
    assert "24" in bot.announcements[0]
    assert repository.has_sent_reminder(conn, week_id, 24) is True


async def test_pregame_reminder_does_not_repeat_the_same_threshold(conn):
    bot = FakeBot(conn)
    week_id = _setup_week_kicking_off_in(conn, hours_from_now=20)
    repository.opt_in(conn, user_id=1, week_id=week_id)

    await jobs.pregame_reminder_job(bot)
    await jobs.pregame_reminder_job(bot)

    assert len(bot.announcements) == 1


async def test_pregame_reminder_skips_the_message_when_nobody_has_balance(conn):
    bot = FakeBot(conn)
    week_id = _setup_week_kicking_off_in(conn, hours_from_now=20)
    repository.opt_in(conn, user_id=1, week_id=week_id)
    conn.execute("UPDATE week_participants SET current_balance = 0")
    conn.commit()

    await jobs.pregame_reminder_job(bot)

    assert bot.announcements == []
    assert repository.has_sent_reminder(conn, week_id, 24) is True  # still marked, no re-checking later


async def test_pregame_reminder_fires_multiple_crossed_thresholds_at_once(conn):
    # simulates the job having been down/off until kickoff was already under an hour away
    bot = FakeBot(conn)
    week_id = _setup_week_kicking_off_in(conn, hours_from_now=0.5)
    repository.opt_in(conn, user_id=1, week_id=week_id)

    await jobs.pregame_reminder_job(bot)

    assert len(bot.announcements) == 2
    assert repository.has_sent_reminder(conn, week_id, 24) is True
    assert repository.has_sent_reminder(conn, week_id, 1) is True


async def test_pregame_reminder_noop_once_kickoff_has_passed(conn):
    bot = FakeBot(conn)
    week_id = _setup_week_kicking_off_in(conn, hours_from_now=-1)
    repository.opt_in(conn, user_id=1, week_id=week_id)

    await jobs.pregame_reminder_job(bot)

    assert bot.announcements == []
