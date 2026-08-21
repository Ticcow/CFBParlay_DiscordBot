import logging
from zoneinfo import ZoneInfo

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from bot.commands import status_panel
from bot.parlays import grading, locking, repository, standings, timeutils
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

    result = grading.grade_week(bot.conn, week["id"])
    winners = standings.finalize_week(bot.conn, week["id"])
    if winners:
        rows = repository.list_week_standings(bot.conn, week["id"])
        lines = [f"🏆 Week {week['week_number']} is final!"]
        for i, row in enumerate(rows, start=1):
            crown = " 🏆" if row["is_weekly_winner"] else ""
            lines.append(f"{i}. <@{row['user_id']}> — ${row['current_balance']:.2f}{crown}")
        await bot.announce("\n".join(lines))
    if result["graded"]:
        await status_panel.refresh(bot)
    return result


async def poll_scores(bot) -> None:
    week = repository.get_latest_week(bot.conn)
    if week is None:
        return
    games = await bot.cfbd.get_games(week["season_year"], week["week_number"], week["season_type"])
    repository.upsert_games(bot.conn, week["id"], games)

    # grade individual legs as their own game finishes, not just once the whole
    # week is done - lets people watch a parlay's legs resolve throughout the day
    graded_legs = grading.grade_pending_legs(bot.conn, week["id"])
    if graded_legs:
        await status_panel.refresh(bot)

    updated = repository.list_games(bot.conn, week["id"])
    if updated and all(game["status"] == "final" for game in updated):
        await grade_week_job(bot)


PREGAME_REMINDER_THRESHOLDS_HOURS = (24, 6, 1)


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
        except Exception:
            logger.exception("Scheduled job %s failed", name)
            try:
                await bot.announce(f"⚠️ Scheduled job `{name}` failed - check the logs.")
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
    scheduler.add_job(_guarded(bot, "poll_scores", poll_scores), CronTrigger(day_of_week="sat", minute="*/45"))
    scheduler.add_job(_guarded(bot, "poll_scores_daily", poll_scores), CronTrigger(hour=8))
    scheduler.add_job(_guarded(bot, "grade_week_fallback", grade_week_job), CronTrigger(day_of_week="sun", hour=8))
    scheduler.add_job(_guarded(bot, "api_usage_report", api_usage_report_job), CronTrigger(day=1, hour=9))
    scheduler.start()
    return scheduler
