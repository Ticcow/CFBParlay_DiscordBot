from datetime import datetime, timedelta, timezone

import httpx
import pytest

from bot.integrations.cfbd_client import CalendarWeek, CfbdGame, RankedTeam
from bot.integrations.odds_client import OddsEvent
from bot.parlays import grading, repository, standings, timeutils, zingers
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
        self.get_games_calls = 0
        self.calendar_error = None

    async def get_calendar(self, year):
        if self.calendar_error is not None:
            raise self.calendar_error
        return self.calendar

    async def get_games(self, year, week, season_type):
        self.get_games_calls += 1
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


def _setup_submitted_parlay_with_one_leg(conn, week_id, user_id, home, away, selection="home"):
    repository.upsert_games(
        conn, week_id, [CfbdGame(1, home, away, "2026-08-29T19:00:00Z", "scheduled", None, None)]
    )
    game, _ = repository.find_game_by_teams(conn, week_id, home, away)
    event = OddsEvent(home, away, "2026-08-29T19:00:00Z", "draftkings", moneyline_home=-150, moneyline_away=130)
    repository.insert_odds_snapshot(conn, game["id"], event, flipped=False)
    snapshot = repository.get_latest_odds_snapshot(conn, game["id"])
    participant = repository.opt_in(conn, user_id=user_id, week_id=week_id)
    parlay_id = repository.start_parlay(conn, user_id, week_id)
    repository.add_leg(conn, parlay_id, game["id"], snapshot["id"], "moneyline", selection, None, -150)
    repository.submit_parlay(conn, parlay_id, participant["id"], 100.0, 166.67)
    return parlay_id, game


async def test_poll_scores_announces_elimination_on_a_fresh_loss(conn):
    bot = FakeBot(conn)
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    parlay_id, _ = _setup_submitted_parlay_with_one_leg(
        conn, week_id, user_id=42, home="Texas", away="Ohio State", selection="home"
    )
    # Texas (home) loses outright
    bot.cfbd.games = [CfbdGame(1, "Texas", "Ohio State", "2026-08-29T19:00:00Z", "final", 10, 24)]

    await jobs.poll_scores(bot)

    # this is the week's only game, so poll_scores also finalizes the week
    # right after - the knockout alert should still be the first message
    assert "KNOCKED OUT" in bot.announcements[0]
    assert "<@42>" in bot.announcements[0]
    assert "Ohio State" in bot.announcements[0]  # names the specific losing pick


async def test_poll_scores_does_not_announce_elimination_on_a_win(conn):
    bot = FakeBot(conn)
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    _setup_submitted_parlay_with_one_leg(
        conn, week_id, user_id=42, home="Texas", away="Ohio State", selection="home"
    )
    bot.cfbd.games = [CfbdGame(1, "Texas", "Ohio State", "2026-08-29T19:00:00Z", "final", 24, 17)]

    await jobs.poll_scores(bot)

    assert not any("KNOCKED OUT" in message for message in bot.announcements)


async def test_poll_scores_stops_polling_and_reannouncing_once_week_is_finalized(conn):
    # once a week's last game finishes and grading wraps it up, poll_scores
    # keeps getting called (gameday runs, the daily 8am catch-all) until a new
    # week opens - it should go quiet immediately instead of re-hitting CFBD
    # and re-posting "week is final" on every one of those later calls
    bot = FakeBot(conn)
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    _setup_submitted_parlay_with_one_leg(
        conn, week_id, user_id=42, home="Texas", away="Ohio State", selection="home"
    )
    bot.cfbd.games = [CfbdGame(1, "Texas", "Ohio State", "2026-08-29T19:00:00Z", "final", 24, 17)]
    bot.cfbd.calendar = []  # no next week published yet - stays on week 1

    await jobs.poll_scores(bot)
    assert bot.cfbd.get_games_calls == 1
    assert any("is final" in m for m in bot.announcements)
    announcements_after_first_run = len(bot.announcements)

    await jobs.poll_scores(bot)
    await jobs.poll_scores(bot)

    assert bot.cfbd.get_games_calls == 1  # never polled CFBD again
    assert len(bot.announcements) == announcements_after_first_run  # no repeat "is final"


async def test_grade_week_job_auto_syncs_next_week_once_finalized(conn):
    bot = FakeBot(conn)
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    _setup_submitted_parlay_with_one_leg(
        conn, week_id, user_id=42, home="Texas", away="Ohio State", selection="home"
    )
    repository.upsert_games(
        conn, week_id, [CfbdGame(1, "Texas", "Ohio State", "2026-08-29T19:00:00Z", "final", 24, 17)]
    )
    # FIXED_NOW (2026-08-28) is before this week's window, so it's picked as
    # the soonest upcoming week once grading tries to advance into it
    bot.cfbd.calendar = [
        CalendarWeek(
            season=2026, week=2, season_type="regular",
            first_game_start="2026-09-01T00:00:00Z", last_game_start="2026-09-07T23:59:00Z",
        )
    ]
    bot.cfbd.games = [CfbdGame(2, "Alabama", "Georgia", "2026-09-05T19:00:00Z", "scheduled", None, None)]

    await jobs.grade_week_job(bot)

    assert any("is final" in m for m in bot.announcements)
    assert any("Week 2" in m and "is open" in m for m in bot.announcements)
    assert repository.get_latest_week(conn)["week_number"] == 2


async def test_grade_week_job_does_not_advance_when_not_yet_finalized(conn):
    bot = FakeBot(conn)
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.upsert_games(
        conn,
        week_id,
        [
            CfbdGame(1, "Texas", "Ohio State", "2026-08-29T19:00:00Z", "final", 24, 17),
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
    participant = repository.opt_in(conn, user_id=1, week_id=week_id)
    parlay_id = repository.start_parlay(conn, 1, week_id)
    texas_snapshot = repository.get_latest_odds_snapshot(conn, texas_game["id"])
    bama_snapshot = repository.get_latest_odds_snapshot(conn, bama_game["id"])
    repository.add_leg(conn, parlay_id, texas_game["id"], texas_snapshot["id"], "moneyline", "home", None, -150)
    repository.add_leg(conn, parlay_id, bama_game["id"], bama_snapshot["id"], "moneyline", "home", None, -150)
    repository.submit_parlay(conn, parlay_id, participant["id"], 100.0, 277.78)
    # Alabama hasn't finished yet, so grading isn't complete

    bot.cfbd.calendar = [make_calendar_week()]  # would advance into this if given the chance

    await jobs.grade_week_job(bot)

    assert bot.announcements == []
    assert repository.get_latest_week(conn)["week_number"] == 1  # no advance


async def test_grade_week_job_finalizes_without_erroring_at_end_of_season(conn):
    bot = FakeBot(conn)
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    _setup_submitted_parlay_with_one_leg(
        conn, week_id, user_id=42, home="Texas", away="Ohio State", selection="home"
    )
    repository.upsert_games(
        conn, week_id, [CfbdGame(1, "Texas", "Ohio State", "2026-08-29T19:00:00Z", "final", 24, 17)]
    )
    bot.cfbd.calendar = []  # nothing left this season

    await jobs.grade_week_job(bot)

    assert any("is final" in m for m in bot.announcements)
    assert repository.get_latest_week(conn)["week_number"] == 1  # nothing to advance into


async def test_grade_week_job_cfbd_hiccup_during_auto_advance_is_not_a_job_failure(conn):
    # the week is already graded and announced by the time it tries to advance -
    # a CFBD timeout there shouldn't post a "job failed" alert on top of that
    bot = FakeBot(conn)
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    _setup_submitted_parlay_with_one_leg(
        conn, week_id, user_id=42, home="Texas", away="Ohio State", selection="home"
    )
    repository.upsert_games(
        conn, week_id, [CfbdGame(1, "Texas", "Ohio State", "2026-08-29T19:00:00Z", "final", 24, 17)]
    )
    bot.cfbd.calendar_error = httpx.ReadTimeout("timed out")

    await jobs._guarded(bot, "poll_scores_daily", jobs.grade_week_job)()

    assert any("is final" in m for m in bot.announcements)
    assert not any("failed" in m for m in bot.announcements)
    assert repository.is_week_finalized(conn, week_id) is True


async def test_evening_digest_noop_with_no_week(conn):
    bot = FakeBot(conn)
    await jobs.evening_digest_job(bot)
    assert bot.announcements == []


async def test_evening_digest_noop_before_any_game_has_started(conn):
    from datetime import timedelta

    bot = FakeBot(conn)
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    future = (FIXED_NOW + timedelta(hours=3)).isoformat().replace("+00:00", "Z")
    repository.upsert_games(
        conn, week_id, [CfbdGame(1, "Texas", "Ohio State", future, "scheduled", None, None)]
    )
    repository.opt_in(conn, user_id=1, week_id=week_id)

    await jobs.evening_digest_job(bot)

    assert bot.announcements == []


async def test_evening_digest_noop_with_no_submitted_parlays(conn):
    bot = FakeBot(conn)
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    past = FIXED_NOW.isoformat().replace("+00:00", "Z")
    repository.upsert_games(
        conn, week_id, [CfbdGame(1, "Texas", "Ohio State", past, "scheduled", None, None)]
    )
    repository.opt_in(conn, user_id=1, week_id=week_id)  # opted in, never actually submitted a parlay

    await jobs.evening_digest_job(bot)

    assert bot.announcements == []


async def test_evening_digest_includes_knocked_out_parlays(conn):
    bot = FakeBot(conn)
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    _setup_submitted_parlay_with_one_leg(
        conn, week_id, user_id=1, home="Texas", away="Ohio State", selection="home"
    )
    repository.upsert_games(
        conn, week_id, [CfbdGame(1, "Texas", "Ohio State", "2026-08-28T00:00:00Z", "final", 10, 24)]
    )
    grading.grade_pending_legs(conn, week_id)  # busts the only leg, parlay isn't finalized/graded yet

    await jobs.evening_digest_job(bot)

    assert len(bot.announcements) == 1
    assert "<@1>" in bot.announcements[0]
    assert "KNOCKED OUT" in bot.announcements[0]


async def test_evening_digest_includes_fully_graded_parlays(conn):
    bot = FakeBot(conn)
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    parlay_id, _ = _setup_submitted_parlay_with_one_leg(
        conn, week_id, user_id=1, home="Texas", away="Ohio State", selection="home"
    )
    repository.upsert_games(
        conn, week_id, [CfbdGame(1, "Texas", "Ohio State", "2026-08-28T00:00:00Z", "final", 10, 24)]
    )
    grading.grade_week(conn, week_id)  # fully finalizes the loss, not just the leg

    await jobs.evening_digest_job(bot)

    assert len(bot.announcements) == 1
    assert "<@1>" in bot.announcements[0]
    assert "[LOSS]" in bot.announcements[0]
    assert "$0 payout" in bot.announcements[0]


async def test_evening_digest_lists_active_parlays_with_payout_and_progress(conn):
    bot = FakeBot(conn)
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.upsert_games(
        conn, week_id, [CfbdGame(1, "Texas", "Ohio State", "2026-08-28T00:00:00Z", "final", 24, 17)]
    )
    game, _ = repository.find_game_by_teams(conn, week_id, "Texas", "Ohio State")
    event = OddsEvent("Texas", "Ohio State", "2026-08-28T00:00:00Z", "draftkings", moneyline_home=-150, moneyline_away=130)
    repository.insert_odds_snapshot(conn, game["id"], event, flipped=False)
    snapshot = repository.get_latest_odds_snapshot(conn, game["id"])
    participant = repository.opt_in(conn, user_id=1, week_id=week_id)
    parlay_id = repository.start_parlay(conn, 1, week_id)
    repository.add_leg(conn, parlay_id, game["id"], snapshot["id"], "moneyline", "home", None, -150)
    repository.submit_parlay(conn, parlay_id, participant["id"], 100.0, 166.67)
    grading.grade_pending_legs(conn, week_id)  # this leg wins, parlay stays active

    await jobs.evening_digest_job(bot)

    assert len(bot.announcements) == 1
    assert "<@1>" in bot.announcements[0]
    assert "$167" in bot.announcements[0]
    assert "1/1 legs decided" in bot.announcements[0]


def _finalize_single_parlay_week_at(conn, monkeypatch, finalized_at):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    _setup_submitted_parlay_with_one_leg(
        conn, week_id, user_id=1, home="Texas", away="Ohio State", selection="home"
    )
    repository.upsert_games(
        conn, week_id, [CfbdGame(1, "Texas", "Ohio State", "2026-08-28T00:00:00Z", "final", 24, 17)]
    )
    monkeypatch.setattr(timeutils, "utc_now", lambda: finalized_at)
    grading.grade_week(conn, week_id)
    assert standings.finalize_week(conn, week_id) == [1]


async def test_evening_digest_posts_final_recap_on_the_day_the_week_finalized(conn, monkeypatch):
    sunday_8am_et = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    _finalize_single_parlay_week_at(conn, monkeypatch, sunday_8am_et)
    bot = FakeBot(conn)

    monkeypatch.setattr(timeutils, "utc_now", lambda: sunday_8am_et + timedelta(hours=11))  # 7pm ET
    await jobs.evening_digest_job(bot)

    assert len(bot.announcements) == 1
    assert "[WIN]" in bot.announcements[0]


async def test_evening_digest_goes_quiet_the_day_after_the_week_finalized(conn, monkeypatch):
    # 11pm ET Sunday and 7pm ET Monday share a UTC date (both Aug 31), so this
    # only passes if "the day it finalized" is judged in Eastern time
    sunday_11pm_et = datetime(2026, 8, 31, 3, 0, tzinfo=timezone.utc)
    _finalize_single_parlay_week_at(conn, monkeypatch, sunday_11pm_et)
    bot = FakeBot(conn)

    monday_7pm_et = datetime(2026, 8, 31, 23, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(timeutils, "utc_now", lambda: monday_7pm_et)
    await jobs.evening_digest_job(bot)

    assert bot.announcements == []


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
    assert "RuntimeError" in bot.announcements[0]
    # never the message - an httpx error's message carries the request URL,
    # which for the Odds API includes the API key
    assert "boom" not in bot.announcements[0]


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


# --- daily trash talk ---

HOWLER = jobs.TRASH_TALK_FAVORITE_USER_ID
EASTERN_8PM = datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc)  # Tue 9/1 8pm ET


def _eastern(hour, minute):
    return datetime(2026, 9, 1, hour, minute, tzinfo=jobs.EASTERN)


def test_trash_talk_slot_odds_spread_one_post_evenly_across_the_window():
    assert jobs.trash_talk_slot_odds(_eastern(10, 30)) == 0
    assert jobs.trash_talk_slot_odds(_eastern(22, 0)) == 0
    assert jobs.trash_talk_slot_odds(_eastern(11, 0)) == 1 / 22
    assert jobs.trash_talk_slot_odds(_eastern(21, 0)) == 1 / 2
    assert jobs.trash_talk_slot_odds(_eastern(21, 30)) == 1  # last slot always fires


def test_pick_trash_talk_target_gives_howler_half_the_picks():
    first = lambda options: options[0]
    assert jobs.pick_trash_talk_target([1, HOWLER, 2], lambda: 0.49, first) == HOWLER
    assert jobs.pick_trash_talk_target([1, HOWLER, 2], lambda: 0.5, first) == 1
    assert jobs.pick_trash_talk_target([HOWLER], lambda: 0.99, first) == HOWLER
    assert jobs.pick_trash_talk_target([1, 2], lambda: 0.0, first) == 1


async def test_trash_talk_job_posts_once_per_day_at_the_picked_player(conn, monkeypatch):
    monkeypatch.setattr(timeutils, "utc_now", lambda: EASTERN_8PM)
    bot = FakeBot(conn)
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.opt_in(conn, user_id=1, week_id=week_id)
    repository.opt_in(conn, user_id=HOWLER, week_id=week_id)

    always = lambda: 0.0
    await jobs.trash_talk_job(bot, random_fn=always, choice_fn=lambda options: options[0])
    await jobs.trash_talk_job(bot, random_fn=always, choice_fn=lambda options: options[0])

    assert len(bot.announcements) == 1
    assert f"<@{HOWLER}>" in bot.announcements[0]


async def test_trash_talk_job_waits_for_its_slot(conn, monkeypatch):
    monkeypatch.setattr(timeutils, "utc_now", lambda: EASTERN_8PM)
    bot = FakeBot(conn)
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.opt_in(conn, user_id=1, week_id=week_id)

    await jobs.trash_talk_job(bot, random_fn=lambda: 0.99)  # 8pm slot odds are 1/4

    assert bot.announcements == []


async def test_trash_talk_job_skips_without_using_up_the_day_when_nobody_opted_in(conn, monkeypatch):
    monkeypatch.setattr(timeutils, "utc_now", lambda: EASTERN_8PM)
    bot = FakeBot(conn)
    week_id = repository.upsert_week(conn, 2026, 1, "regular")

    await jobs.trash_talk_job(bot, random_fn=lambda: 0.0)
    repository.opt_in(conn, user_id=1, week_id=week_id)
    await jobs.trash_talk_job(bot, random_fn=lambda: 0.0, choice_fn=lambda options: options[0])

    assert len(bot.announcements) == 1


async def test_trash_talk_job_can_name_the_targets_busted_bet(conn, monkeypatch):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    _setup_submitted_parlay_with_one_leg(conn, week_id, user_id=1, home="Texas", away="Ohio State")
    repository.upsert_games(
        conn, week_id, [CfbdGame(1, "Texas", "Ohio State", "2026-08-29T19:00:00Z", "final", 10, 24)]
    )
    grading.grade_pending_legs(conn, week_id)
    monkeypatch.setattr(timeutils, "utc_now", lambda: EASTERN_8PM)
    bot = FakeBot(conn)

    def pick_busted_category(options):
        if zingers._TRASH_TALK_BUSTED_BET in options:
            return zingers._TRASH_TALK_BUSTED_BET
        return options[0]

    await jobs.trash_talk_job(bot, random_fn=lambda: 0.0, choice_fn=pick_busted_category)

    assert "Texas (-150)" in bot.announcements[0]


async def test_trash_talk_job_never_ranks_players_mid_week(conn, monkeypatch):
    # everyone all-in mid-week sits at $0 - nobody is "last place" yet
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    _setup_submitted_parlay_with_one_leg(conn, week_id, user_id=1, home="Texas", away="Ohio State")
    repository.opt_in(conn, user_id=2, week_id=week_id)
    monkeypatch.setattr(timeutils, "utc_now", lambda: EASTERN_8PM)
    offered = []

    def record_categories(options):
        if options and isinstance(options[0], list):
            offered.extend(options)
        return options[0]

    bot = FakeBot(conn)
    await jobs.trash_talk_job(bot, random_fn=lambda: 0.0, choice_fn=record_categories)

    assert bot.announcements
    assert zingers._TRASH_TALK_LAST_PLACE not in offered
    assert zingers._TRASH_TALK_LEADER not in offered


async def test_trash_talk_job_calls_out_last_place_once_the_week_is_settled(conn, monkeypatch):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    _setup_submitted_parlay_with_one_leg(conn, week_id, user_id=1, home="Texas", away="Ohio State")
    repository.opt_in(conn, user_id=2, week_id=week_id)
    repository.upsert_games(
        conn, week_id, [CfbdGame(1, "Texas", "Ohio State", "2026-08-29T19:00:00Z", "final", 24, 17)]
    )
    grading.grade_week(conn, week_id)
    standings.finalize_week(conn, week_id)  # user 1 won $167, user 2 never bet -> $0
    monkeypatch.setattr(timeutils, "utc_now", lambda: EASTERN_8PM)

    def pick_user_2_and_last_place(options):
        if zingers._TRASH_TALK_LAST_PLACE in options:
            return zingers._TRASH_TALK_LAST_PLACE
        return 2 if 2 in options else options[0]

    bot = FakeBot(conn)
    await jobs.trash_talk_job(bot, random_fn=lambda: 0.0, choice_fn=pick_user_2_and_last_place)

    assert "<@2>" in bot.announcements[0]
    assert "$0" in bot.announcements[0]


async def test_post_trash_talk_posts_on_demand_even_after_the_daily_one(conn, monkeypatch):
    # the panel button isn't limited by the once-a-day schedule
    monkeypatch.setattr(timeutils, "utc_now", lambda: EASTERN_8PM)
    bot = FakeBot(conn)
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.opt_in(conn, user_id=1, week_id=week_id)
    await jobs.trash_talk_job(bot, random_fn=lambda: 0.0)

    assert await jobs.post_trash_talk(bot) is True
    assert await jobs.post_trash_talk(bot) is True
    assert len(bot.announcements) == 3


async def test_post_trash_talk_does_nothing_with_nobody_opted_in(conn):
    bot = FakeBot(conn)
    repository.upsert_week(conn, 2026, 1, "regular")

    assert await jobs.post_trash_talk(bot) is False
    assert bot.announcements == []


async def test_post_trash_talk_doesnt_repeat_a_line_until_the_pool_runs_dry(conn):
    bot = FakeBot(conn)
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    _setup_submitted_parlay_with_one_leg(conn, week_id, user_id=1, home="Texas", away="Ohio State")

    for _ in range(jobs.TRASH_TALK_RECENT_LIMIT):
        await jobs.post_trash_talk(bot)

    assert len(set(bot.announcements)) == jobs.TRASH_TALK_RECENT_LIMIT


async def test_post_trash_talk_uses_custom_roasts(conn):
    bot = FakeBot(conn)
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    _setup_submitted_parlay_with_one_leg(conn, week_id, user_id=1, home="Texas", away="Ohio State")
    repository.add_custom_roast(conn, "generic", "{user} custom-only line", added_by=7)

    await jobs.post_trash_talk(bot, choice_fn=lambda options: options[-1])

    assert bot.announcements == ["<@1> custom-only line"]


async def test_knockout_alert_can_use_a_custom_knockout_roast(conn, monkeypatch):
    bot = FakeBot(conn)
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    _setup_submitted_parlay_with_one_leg(conn, week_id, user_id=42, home="Texas", away="Ohio State")
    repository.add_custom_roast(conn, "knockout", "{user} custom knockout on {bet}", added_by=7)
    real_zinger = zingers.get_knockout_zinger
    monkeypatch.setattr(
        zingers, "get_knockout_zinger",
        lambda mention, bet, custom=(): real_zinger(mention, bet, custom, choice_fn=lambda o: o[-1]),
    )
    bot.cfbd.games = [CfbdGame(1, "Texas", "Ohio State", "2026-08-29T19:00:00Z", "final", 10, 24)]

    await jobs.poll_scores(bot)

    assert "<@42> custom knockout on Texas (-150)" in bot.announcements[0]
