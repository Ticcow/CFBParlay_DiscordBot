import logging
import random
from datetime import date, datetime
from zoneinfo import ZoneInfo

import discord
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from bot.commands import status_panel
from bot.parlays import formatting, grading, locking, repository, standings, timeutils, zingers
from bot.scheduler import season

logger = logging.getLogger("degen_bot.scheduler")

EASTERN = ZoneInfo("America/New_York")


async def sync_week_games(bot) -> int | None:
    """Auto-detects and syncs whatever CFBD week is current right now. Returns
    the synced week's id, or None if the calendar has no current/upcoming week
    (off-season)."""
    now = timeutils.utc_now()
    calendar = await bot.cfbd.get_calendar(season.season_year_for(now))
    target = season.determine_current_week(calendar, now)
    if target is None:
        return None

    already_synced = repository.get_week_by_number(
        bot.conn, target.season, target.week, target.season_type
    )
    games = await bot.cfbd.get_games(target.season, target.week, target.season_type)
    week_id = repository.upsert_week(bot.conn, target.season, target.week, target.season_type)
    repository.upsert_games(bot.conn, week_id, games)

    ranked_teams = await bot.cfbd.get_ap_top25(target.season, target.week, target.season_type)
    repository.replace_rankings(bot.conn, week_id, ranked_teams)

    if already_synced is None:
        await bot.announce(
            f"📅 Week {target.week} ({target.season_type}) is open - {len(games)} games "
            "synced. Use /optin to join!"
        )
    await status_panel.refresh(bot)
    return week_id


async def fetch_odds(bot) -> None:
    week = repository.get_latest_week(bot.conn)
    if week is None:
        return
    events = await bot.odds.get_ncaaf_odds()
    repository.sync_odds_for_week(bot.conn, week["id"], events)


async def lock_check_job(bot) -> dict:
    result = locking.lock_check(bot.conn)
    for user_id, parlay_id in result["expired_drafts"]:
        try:
            user = await bot.fetch_user(user_id)
            await user.send(
                f"Your draft parlay #{parlay_id} was cancelled - one of its games "
                "kicked off before you submitted."
            )
        except discord.HTTPException:
            pass  # best-effort DM; a closed DM or unknown user shouldn't fail the job

    # only refresh when something actually changed - this runs every 5 min, and
    # reposting an unchanged panel every cycle would just be noise
    if result["locked"] or result["expired_drafts"]:
        await status_panel.refresh(bot)
    return result


async def grade_week_job(bot) -> dict:
    week = repository.get_latest_week(bot.conn)
    if week is None:
        return {"graded": [], "skipped_incomplete": []}
    if repository.is_week_finalized(bot.conn, week["id"]):
        return {"graded": [], "skipped_incomplete": []}  # already wrapped up

    # grade_week only finalizes a parlay once every one of its legs is final,
    # so a leg that just went final on its own (e.g. this job running as the
    # Sunday fallback or via /admin grade-week, without poll_scores having
    # graded it incrementally first) still needs its own knockout alert -
    # a no-op if poll_scores already got to it, since grade_pending_legs
    # skips anything no longer "pending".
    await _grade_pending_and_announce(bot, week["id"])

    result = grading.grade_week(bot.conn, week["id"])
    winners = standings.finalize_week(bot.conn, week["id"])
    if winners:
        rows = repository.list_week_standings(bot.conn, week["id"])
        lines = [f"🏆 Week {week['week_number']} is final!"]
        for i, row in enumerate(rows, start=1):
            crown = " 🏆" if row["is_weekly_winner"] else ""
            lines.append(f"{i}. <@{row['user_id']}> — {formatting.format_dollars(row['current_balance'])}{crown}")
        await bot.announce("\n".join(lines))

    if result["graded"]:
        await status_panel.refresh(bot)

    if winners:
        # the week just wrapped up - try to roll straight into whatever CFBD
        # has lined up next instead of waiting for Tuesday's scheduled sync.
        # Only best-effort: CFBD's calendar usually still counts the finished
        # week as current on Sunday, so this often just re-syncs it, and the
        # Tuesday cron opens the next week either way. A CFBD hiccup here
        # shouldn't turn an already-graded, already-announced week into a
        # "job failed" alert.
        try:
            await sync_week_games(bot)
        except httpx.HTTPError:
            logger.exception("Auto-advance after finalizing week %s failed", week["week_number"])

    return result


def _elimination_message(entry: dict) -> str:
    mention = f"<@{entry['user_id']}>"
    leg = entry["leg"]
    bet = formatting.format_selection_button_label(
        leg, leg["market"], leg["selection"], leg["line_value"], leg["price_american"]
    )
    return (
        f"🥊 {mention}'s parlay has been KNOCKED OUT!\n"
        f"{formatting.format_leg(leg)}\n"
        f"{zingers.get_knockout_zinger(mention, bet)}"
    )


async def _grade_pending_and_announce(bot, week_id: int) -> list[dict]:
    """Grades whatever legs just went final and posts a one-time knockout
    alert for each parlay's first losing leg - shared by poll_scores (which
    catches most eliminations as they happen live) and grade_week_job (the
    Sunday fallback / manual /admin grade-week path), so a knockout gets
    announced no matter which one actually ends up grading it."""
    graded_legs = grading.grade_pending_legs(bot.conn, week_id)
    for entry in graded_legs:
        if entry["result"] == "loss" and not entry["already_had_loss"]:
            await bot.announce(_elimination_message(entry))
    return graded_legs


async def poll_scores(bot) -> None:
    week = repository.get_latest_week(bot.conn)
    if week is None:
        return
    if repository.is_week_finalized(bot.conn, week["id"]):
        # nothing left to grade or announce until a new week opens - skip the
        # CFBD call entirely rather than re-polling a settled week on every
        # gameday run (and Sunday's daily catch-all) until Tuesday's sync
        # finally rolls the panel over to whatever's next
        return
    games = await bot.cfbd.get_games(week["season_year"], week["week_number"], week["season_type"])
    repository.upsert_games(bot.conn, week["id"], games)

    # grade individual legs as their own game finishes, not just once the whole
    # week is done - lets people watch a parlay's legs resolve throughout the day
    graded_legs = await _grade_pending_and_announce(bot, week["id"])

    if graded_legs:
        await status_panel.refresh(bot)

    updated = repository.list_games(bot.conn, week["id"])
    if updated and all(game["status"] == "final" for game in updated):
        await grade_week_job(bot)


PREGAME_REMINDER_THRESHOLDS_HOURS = (24, 1)


async def pregame_reminder_job(bot) -> None:
    """Nags opted-in players who still have unspent bankroll as the week's
    first kickoff approaches, at each threshold in PREGAME_REMINDER_THRESHOLDS_HOURS.
    Each threshold fires at most once per week (tracked in week_reminders_sent),
    regardless of how many times this job runs."""
    week = repository.get_latest_week(bot.conn)
    if week is None:
        return
    earliest = repository.get_earliest_kickoff(bot.conn, week["id"])
    if earliest is None:
        return

    now = timeutils.utc_now()
    kickoff = timeutils.parse_utc(earliest)
    if kickoff <= now:
        return  # the week has already started - nothing left to remind anyone about

    hours_until = (kickoff - now).total_seconds() / 3600

    for threshold in PREGAME_REMINDER_THRESHOLDS_HOURS:
        if hours_until > threshold:
            continue
        if repository.has_sent_reminder(bot.conn, week["id"], threshold):
            continue
        repository.mark_reminder_sent(bot.conn, week["id"], threshold)

        user_ids = repository.list_user_ids_with_balance(bot.conn, week["id"])
        if not user_ids:
            continue
        mentions = " ".join(f"<@{user_id}>" for user_id in user_ids)
        hour_word = "hour" if threshold == 1 else "hours"
        await bot.announce(
            f"⏰ Week {week['week_number']} kicks off in about {threshold} {hour_word} - "
            f"get your bets in! {mentions}"
        )


def _eastern_date(moment: datetime) -> date:
    return moment.astimezone(EASTERN).date()


async def evening_digest_job(bot) -> None:
    """A once-a-day bulk roundup of every submitted parlay - alive, knocked
    out, or fully graded - who it belongs to, its payout (potential or
    actual), and how many of its legs are already decided. Silently skips if
    the week's games haven't started yet, or if nobody has submitted
    anything to report on - no news is no message, not an empty one.

    Once the week is finalized, it posts one last recap on the day that
    happened (normally Sunday) and then goes quiet - the finished week stays
    "current" until Tuesday's sync opens the next one, and repeating the
    same final results every evening until then is just noise."""
    week = repository.get_latest_week(bot.conn)
    if week is None:
        return
    finalized_at = repository.get_week_finalized_at(bot.conn, week["id"])
    if finalized_at is not None and _eastern_date(finalized_at) < _eastern_date(timeutils.utc_now()):
        return
    earliest = repository.get_earliest_kickoff(bot.conn, week["id"])
    if earliest is None or timeutils.parse_utc(earliest) > timeutils.utc_now():
        return  # nothing has kicked off yet this week

    submitted = repository.list_submitted_parlays_for_week(bot.conn, week["id"])
    if not submitted:
        return

    lines = [f"📋 **Parlay Update — Week {week['week_number']}**"]
    for parlay in submitted:
        legs = repository.list_legs_with_games(bot.conn, parlay["id"])
        decided = sum(1 for leg in legs if leg["result"] != "pending")
        wager = f"{formatting.format_dollars(parlay['wager_dollars'])}"
        mention = f"<@{parlay['user_id']}>"

        if parlay["status"] == "graded":
            payout_text, status_label = formatting.format_payout_and_status(parlay)
            marker = {"win": "🏆", "loss": "💀", "push": "➖"}[parlay["result"]]
            lines.append(f"{marker} {mention} — {wager} wager → {payout_text} [{status_label}]")
        elif any(leg["result"] == "loss" for leg in legs):
            lines.append(
                f"💀 {mention} — {wager} wager → KNOCKED OUT ({decided}/{len(legs)} legs decided)"
            )
        else:
            potential = f"{formatting.format_dollars(parlay['potential_payout_dollars'])}"
            lines.append(
                f"🏈 {mention} — {wager} wager → {potential} potential ({decided}/{len(legs)} legs decided)"
            )
    await bot.announce("\n".join(lines))


# Daily unprompted trash talk: one post per day at a random half-hour between
# 11:00 and 21:30 Eastern, at an opted-in player - Howler gets half the picks.
TRASH_TALK_FAVORITE_USER_ID = 396532921856688128  # Howler (.triinity)
TRASH_TALK_FAVORITE_ODDS = 0.5
TRASH_TALK_FIRST_SLOT_MINUTES = 11 * 60
TRASH_TALK_LAST_SLOT_MINUTES = 21 * 60 + 30
_TRASH_TALK_STATE_KEY = "trash_talk_last_posted_on"


def trash_talk_slot_odds(now_eastern: datetime) -> float:
    """Chance this half-hour slot should be the day's trash-talk post: 1/(slots
    left today, this one included), so exactly one slot fires per day and
    every slot in the window is equally likely to be the one. 0 outside the
    window."""
    minutes = now_eastern.hour * 60 + now_eastern.minute
    if not TRASH_TALK_FIRST_SLOT_MINUTES <= minutes <= TRASH_TALK_LAST_SLOT_MINUTES:
        return 0.0
    slots_left = (TRASH_TALK_LAST_SLOT_MINUTES - minutes) // 30 + 1
    return 1 / slots_left


def pick_trash_talk_target(user_ids: list[int], random_fn=random.random, choice_fn=random.choice) -> int:
    others = [user_id for user_id in user_ids if user_id != TRASH_TALK_FAVORITE_USER_ID]
    favorite_in = len(others) < len(user_ids)
    if favorite_in and (not others or random_fn() < TRASH_TALK_FAVORITE_ODDS):
        return TRASH_TALK_FAVORITE_USER_ID
    return choice_fn(others)


async def trash_talk_job(bot, random_fn=random.random, choice_fn=random.choice) -> None:
    now = timeutils.utc_now()
    today = _eastern_date(now).isoformat()
    if repository.get_state(bot.conn, _TRASH_TALK_STATE_KEY) == today:
        return
    if random_fn() >= trash_talk_slot_odds(now.astimezone(EASTERN)):
        return
    if await post_trash_talk(bot, random_fn, choice_fn):
        repository.set_state(bot.conn, _TRASH_TALK_STATE_KEY, today)
    # else nobody's opted in yet - try again in the next slot


async def post_trash_talk(bot, random_fn=random.random, choice_fn=random.choice) -> bool:
    """Roasts one opted-in player right now (Howler-weighted, see
    pick_trash_talk_target). Shared by the daily job and the panel's Talk
    Shit button. Returns False if there's nobody opted in to roast."""
    week = repository.get_latest_week(bot.conn)
    if week is None:
        return False
    standings = repository.list_week_standings(bot.conn, week["id"])
    if not standings:
        return False

    target = pick_trash_talk_target([row["user_id"] for row in standings], random_fn, choice_fn)
    row = next(r for r in standings if r["user_id"] == target)
    parlays = [
        p for p in repository.list_submitted_parlays_for_week(bot.conn, week["id"]) if p["user_id"] == target
    ]
    busted_bets = [
        formatting.format_selection_button_label(
            leg, leg["market"], leg["selection"], leg["line_value"], leg["price_american"]
        )
        for parlay in parlays
        for leg in repository.list_legs_with_games(bot.conn, parlay["id"])
        if leg["result"] == "loss"
    ]
    # mid-week a balance is just unwagered money (everyone all-in sits at $0),
    # so first/last place only mean something once the week is settled - and
    # never when the whole field is tied
    balances = [r["current_balance"] for r in standings]
    ranked = repository.is_week_finalized(bot.conn, week["id"]) and max(balances) != min(balances)
    message = zingers.get_trash_talk(
        f"<@{target}>",
        formatting.format_dollars(row["current_balance"]),
        busted_bets,
        has_bets=bool(parlays),
        is_last=ranked and row["current_balance"] == min(balances),
        is_leader=ranked and row["current_balance"] == max(balances),
        choice_fn=choice_fn,
    )
    await bot.announce(message)
    return True


async def channel_cleanup_job(bot) -> int:
    return await status_panel.cleanup_channel(bot)


async def api_usage_report_job(bot) -> None:
    rows = repository.get_monthly_api_usage(bot.conn)
    if not rows:
        return
    lines = ["📊 API usage this month:"]
    for row in rows:
        lines.append(f"- {row['service']}: {row['total_credits']} credits ({row['calls']} calls)")
    await bot.announce("\n".join(lines))


def _guarded(bot, name: str, job):
    async def run():
        try:
            await job(bot)
        except Exception as error:
            logger.exception("Scheduled job %s failed", name)
            # the exception type, not its message: the Pi's journal rotates
            # within days, so the alert is often the only lasting record of
            # what went wrong, but httpx messages include the full request URL
            # and the Odds API key rides in that URL's query string
            try:
                await bot.announce(
                    f"⚠️ Scheduled job `{name}` failed ({type(error).__name__}) - check the logs."
                )
            except Exception:
                logger.exception("Also failed to post the failure alert for %s", name)

    return run


def register_jobs(bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=EASTERN)
    scheduler.add_job(_guarded(bot, "sync_week_games", sync_week_games), CronTrigger(day_of_week="tue", hour=6))
    scheduler.add_job(_guarded(bot, "fetch_odds", fetch_odds), CronTrigger(day_of_week="tue", hour=9))
    scheduler.add_job(_guarded(bot, "fetch_odds", fetch_odds), CronTrigger(day_of_week="fri", hour=16))
    scheduler.add_job(_guarded(bot, "lock_check", lock_check_job), IntervalTrigger(minutes=5))
    scheduler.add_job(_guarded(bot, "pregame_reminder", pregame_reminder_job), IntervalTrigger(minutes=5))
    scheduler.add_job(_guarded(bot, "channel_cleanup", channel_cleanup_job), IntervalTrigger(minutes=5))
    scheduler.add_job(
        _guarded(bot, "poll_scores_gameday", poll_scores),
        CronTrigger(day_of_week="thu,fri,sat,sun", hour="12,18,23"),
    )
    scheduler.add_job(_guarded(bot, "poll_scores_daily", poll_scores), CronTrigger(hour=8))
    scheduler.add_job(_guarded(bot, "grade_week_fallback", grade_week_job), CronTrigger(day_of_week="sun", hour=8))
    scheduler.add_job(_guarded(bot, "evening_digest", evening_digest_job), CronTrigger(hour=19))
    scheduler.add_job(_guarded(bot, "trash_talk", trash_talk_job), CronTrigger(minute="0,30"))
    scheduler.add_job(_guarded(bot, "api_usage_report", api_usage_report_job), CronTrigger(day=1, hour=9))
    scheduler.start()
    return scheduler
