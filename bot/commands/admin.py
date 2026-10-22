import random
from datetime import timedelta

import discord
import httpx
from discord import app_commands
from discord.ext import commands

from bot.commands import status_panel
from bot.integrations import team_aliases
from bot.integrations.cfbd_client import CfbdGame, RankedTeam
from bot.integrations.odds_client import OddsEvent
from bot.parlays import repository, timeutils, zingers
from bot.scheduler import jobs as scheduler_jobs
from bot.scheduler import season

SEASON_TYPE_CHOICES = [
    app_commands.Choice(name="regular", value="regular"),
    app_commands.Choice(name="postseason", value="postseason"),
]

# A synthetic week for testing without waiting on real games/odds - season_year
# 9999 can never collide with a real CFBD week, and the sentinel cfbd_game_ids
# below can never collide with real (always-positive, much smaller) CFBD ids.
TEST_SEASON_YEAR = 9999
TEST_WEEK_NUMBER = 1
TEST_SEASON_TYPE = "regular"
TEST_GAMES = [
    # (cfbd_game_id, home, away, minutes_from_now) - real team names so cached
    # logos (via /admin sync-teams) and the Top 25 view both have something to show
    (900000001, "Georgia", "Marshall", 5),
    (900000002, "Ohio State", "Youngstown State", 10),
    (900000003, "Alabama", "Western Kentucky", 120),
    (900000004, "Michigan", "Fresno State", 180),
    (900000005, "Notre Dame", "Navy", 1440),
    (900000006, "Texas", "Rice", 2880),
]
TEST_RANKINGS = [(1, "Georgia"), (2, "Ohio State"), (3, "Alabama"), (4, "Michigan"), (5, "Notre Dame")]

# Most of /admin (sync, refresh, grade, adding a roast) is open to anyone.
# These users alone can do what isn't safe to leave open: resetting a week
# deletes real bets, and removing roasts is moderation.
TRUSTED_ADMIN_USER_IDS = {
    151856216858034176,  # Tenenbaum
    151910709322711040,  # Ticcow
}


def _get_test_week(bot):
    """The synthetic test week specifically, never "whatever week is latest" -
    test-only commands must never be able to touch real CFBD-synced data, even
    if a real week got synced while a test week was still active."""
    return repository.get_week_by_number(bot.conn, TEST_SEASON_YEAR, TEST_WEEK_NUMBER, TEST_SEASON_TYPE)


def _random_final_score() -> tuple[int, int]:
    home = random.randint(10, 45)
    away = random.randint(10, 45)
    while away == home:  # CFB games can't end in a tie
        away = random.randint(10, 45)
    return home, away


async def _do_sync_week(bot) -> tuple[int | None, str]:
    """Auto-detects and syncs whatever CFBD week is current. Returns
    (week_id, message) - week_id is None if the calendar has no current/
    upcoming week (off-season)."""
    week_id = await scheduler_jobs.sync_week_games(bot)
    if week_id is None:
        return None, (
            "No current CFBD week found - probably off-season, or CFBD hasn't "
            "published this year's calendar yet."
        )
    week_row = repository.get_week(bot.conn, week_id)
    games = repository.list_games(bot.conn, week_id)
    return week_id, (
        f"Synced Week {week_row['week_number']} ({week_row['season_type']}, "
        f"{week_row['season_year']}) - {len(games)} games."
    )


async def _do_sync_teams(bot) -> str:
    year = season.season_year_for(timeutils.utc_now())
    teams = await bot.cfbd.get_teams(year)
    repository.upsert_team_logos(bot.conn, teams)
    return f"Cached logos for {len(teams)} teams."


UNMATCHED_ODDS_DISPLAY_LIMIT = 15


def _format_odds_result(result: repository.OddsSyncResult) -> str:
    message = f"Matched odds for {result.matched} game(s)."
    if result.unmatched:
        # cap what's shown - a real mismatch list this long is rare, but since
        # FBS-only filtering trimmed the games table, most "unmatched" odds
        # events these days are just non-FBS opponents we don't track at all,
        # and Discord hard-rejects any message over 2000 characters
        shown = result.unmatched[:UNMATCHED_ODDS_DISPLAY_LIMIT]
        unmatched_list = "\n".join(f"- {away} vs {home}" for home, away in shown)
        message += (
            f"\n\n{len(result.unmatched)} event(s) couldn't be matched to a synced game - "
            "usually just a non-FBS opponent we don't track, occasionally a real team name "
            f"mismatch fixable with /admin add-alias:\n{unmatched_list}"
        )
        if len(result.unmatched) > UNMATCHED_ODDS_DISPLAY_LIMIT:
            message += f"\n...and {len(result.unmatched) - UNMATCHED_ODDS_DISPLAY_LIMIT} more."
    return message


async def _do_refresh_odds(bot, week_id: int) -> str:
    events = await bot.odds.get_ncaaf_odds()
    result = repository.sync_odds_for_week(bot.conn, week_id, events)
    return _format_odds_result(result)


async def handle_sync_week(interaction: discord.Interaction) -> None:
    """The auto-detect path only (no year/week override - a button can't take
    args). Shared by /admin sync-week (called with no args) and the panel's
    Sync All button."""
    bot = interaction.client
    await interaction.response.defer(ephemeral=True, thinking=True)
    _, message = await _do_sync_week(bot)
    await interaction.followup.send(message, ephemeral=True)


async def handle_sync_teams(interaction: discord.Interaction) -> None:
    bot = interaction.client
    await interaction.response.defer(ephemeral=True, thinking=True)
    message = await _do_sync_teams(bot)
    await interaction.followup.send(message, ephemeral=True)


async def handle_refresh_odds(interaction: discord.Interaction) -> None:
    bot = interaction.client
    await interaction.response.defer(ephemeral=True, thinking=True)
    week = repository.get_latest_week(bot.conn)
    if week is None:
        await interaction.followup.send(
            "No week has been synced yet - run /admin sync-week first.", ephemeral=True
        )
        return
    message = await _do_refresh_odds(bot, week["id"])
    await interaction.followup.send(message[:2000], ephemeral=True)


async def handle_sync_all(interaction: discord.Interaction) -> None:
    """Runs sync-week, sync-teams, and refresh-odds back to back - one click
    for the common "get everything current" case instead of three. Shared by
    /admin sync-all and the panel's Sync All button."""
    bot = interaction.client
    await interaction.response.defer(ephemeral=True, thinking=True)

    week_id, week_message = await _do_sync_week(bot)
    lines = [f"1️⃣ {week_message}"]

    teams_message = await _do_sync_teams(bot)
    lines.append(f"2️⃣ {teams_message}")

    if week_id is None:
        lines.append("3️⃣ Skipped odds refresh - no week to attach them to.")
    else:
        odds_message = await _do_refresh_odds(bot, week_id)
        lines.append(f"3️⃣ {odds_message}")

    await interaction.followup.send("\n\n".join(lines)[:2000], ephemeral=True)


async def handle_refresh_panel(interaction: discord.Interaction) -> None:
    await status_panel.refresh(interaction.client)
    await interaction.response.send_message("Panel refreshed.", ephemeral=True)


async def handle_refresh_scores(interaction: discord.Interaction) -> None:
    """Manually runs the same score-poll + grading pass poll_scores does on
    its own schedule - lets someone pull the trigger immediately instead of
    waiting for the next gameday check if a game just finished and the panel
    hasn't caught up yet."""
    bot = interaction.client
    await interaction.response.defer(ephemeral=True, thinking=True)
    week = repository.get_latest_week(bot.conn)
    if week is None:
        await interaction.followup.send("No week is open yet.", ephemeral=True)
        return

    try:
        await scheduler_jobs.poll_scores(bot)
    except httpx.HTTPError:
        await interaction.followup.send(
            "CollegeFootballData's API didn't respond in time - it's probably just "
            "under heavy load on gameday. Try again in a minute.",
            ephemeral=True,
        )
        return

    games = repository.list_games(bot.conn, week["id"])
    final_count = sum(1 for g in games if g["status"] == "final")
    await interaction.followup.send(
        f"Scores refreshed - {final_count}/{len(games)} games final.", ephemeral=True
    )


async def handle_add_roast(interaction: discord.Interaction, category: str, roast: str) -> None:
    """Adds a line to the roast pool - shared by /admin add-roast and the
    panel's Add Roast button. Open to everyone so the whole group can
    contribute; removing lines stays with TRUSTED_ADMIN_USER_IDS."""
    roast = roast.strip()
    problem = zingers.validate_roast_template(category, roast)
    if problem:
        await interaction.response.send_message(f"Couldn't add that: {problem}", ephemeral=True)
        return
    roast_id = repository.add_custom_roast(interaction.client.conn, category, roast, interaction.user.id)
    if roast_id is None:
        await interaction.response.send_message("That exact line is already in the pool.", ephemeral=True)
        return
    preview = roast.format(user=interaction.user.mention, balance="$1,234", bet="Texas -6.5 (-110)")
    label = zingers.ROAST_CATEGORIES[category][1]
    await interaction.response.send_message(
        f"Added roast #{roast_id} ({label}). Preview:\n> {preview}", ephemeral=True
    )


_ROAST_PLACEHOLDER_HINTS = {
    "user": "{user} = the @mention",
    "balance": "{balance} = their dollars",
    "bet": "{bet} = the losing pick",
}


class AddRoastModal(discord.ui.Modal, title="Add a roast"):
    roast = discord.ui.TextInput(
        label="Your roast",
        style=discord.TextStyle.paragraph,
        placeholder="{user} bets like a raccoon in a casino",
        max_length=zingers.MAX_ROAST_LENGTH,
    )

    def __init__(self, category: str):
        super().__init__()
        self.category = category
        allowed = zingers.ROAST_CATEGORIES[category][2]
        hints = ", ".join(_ROAST_PLACEHOLDER_HINTS[name] for name in ("user", "balance", "bet") if name in allowed)
        self.roast.placeholder = f"Use {hints}"[:100]

    async def on_submit(self, interaction: discord.Interaction):
        await handle_add_roast(interaction, self.category, self.roast.value)


class AddRoastCategoryView(discord.ui.View):
    """Step one of the panel's Add Roast flow - a modal can't hold a dropdown,
    so the category gets picked here first, then the modal collects the line."""

    def __init__(self):
        super().__init__(timeout=180)
        select = discord.ui.Select(
            placeholder="When should this roast come up?",
            options=[
                discord.SelectOption(
                    label=label,
                    value=key,
                    description=", ".join(f"{{{name}}}" for name in ("user", "balance", "bet") if name in allowed),
                )
                for key, (_, label, allowed) in zingers.ROAST_CATEGORIES.items()
            ],
        )
        select.callback = self._on_select
        self.add_item(select)
        self._select = select

    async def _on_select(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AddRoastModal(self._select.values[0]))


async def handle_open_add_roast(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        "Pick when your roast should come up, then write it. Use `{user}` where the @mention goes.",
        view=AddRoastCategoryView(),
        ephemeral=True,
    )


async def handle_reset_week(interaction: discord.Interaction) -> None:
    if interaction.user.id not in TRUSTED_ADMIN_USER_IDS:
        await interaction.response.send_message(
            "Only Tenenbaum or Ticcow can reset a week.", ephemeral=True
        )
        return

    bot = interaction.client
    await interaction.response.defer(ephemeral=True, thinking=True)
    week = repository.get_latest_week(bot.conn)
    if week is None:
        await interaction.followup.send("No week is open yet.", ephemeral=True)
        return

    result = repository.reset_week_bets(bot.conn, week["id"])
    await interaction.followup.send(
        f"Reset Week {week['week_number']} - removed {result['parlays_removed']} parlay(s) "
        f"and {result['participants_removed']} opt-in(s). Games/odds/rankings are untouched, "
        "so everyone can /optin fresh without waiting on a re-sync.",
        ephemeral=True,
    )
    await status_panel.refresh(bot)


class AdminCog(commands.GroupCog, name="admin"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()

    @app_commands.command(
        name="sync-week",
        description="Pull the current week's games from CollegeFootballData (or override to a specific week)",
    )
    @app_commands.describe(
        year="Override: season year, e.g. 2026 (auto-detected if left blank)",
        week="Override: week number (auto-detected if left blank)",
        season_type="Override: regular or postseason (defaults to regular)",
    )
    @app_commands.choices(season_type=SEASON_TYPE_CHOICES)
    async def sync_week(
        self,
        interaction: discord.Interaction,
        year: int | None = None,
        week: int | None = None,
        season_type: app_commands.Choice[str] | None = None,
    ):
        if year is None and week is None:
            # the common case: no args at all, just auto-sync whatever CFBD
            # says is the current/coming week - this is the same path the
            # panel's Sync Week button uses, since a button can't take args
            await handle_sync_week(interaction)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        if year is None or week is None:
            await interaction.followup.send(
                "Provide both year and week to sync a specific week, or leave both blank "
                "to auto-sync the current week.",
                ephemeral=True,
            )
            return

        season_type_value = season_type.value if season_type else "regular"
        games = await self.bot.cfbd.get_games(year, week, season_type_value)
        week_id = repository.upsert_week(self.bot.conn, year, week, season_type_value)
        repository.upsert_games(self.bot.conn, week_id, games)
        ranked_teams = await self.bot.cfbd.get_ap_top25(year, week, season_type_value)
        repository.replace_rankings(self.bot.conn, week_id, ranked_teams)
        await interaction.followup.send(
            f"Synced {len(games)} games for {season_type_value} week {week}, {year}.",
            ephemeral=True,
        )

    @app_commands.command(
        name="refresh-odds", description="Pull the current week's odds from The Odds API"
    )
    async def refresh_odds(self, interaction: discord.Interaction):
        await handle_refresh_odds(interaction)

    @app_commands.command(
        name="sync-all",
        description="Run sync-week, sync-teams, and refresh-odds back to back",
    )
    async def sync_all(self, interaction: discord.Interaction):
        await handle_sync_all(interaction)

    @app_commands.command(
        name="add-alias",
        description="Map a team name from The Odds API to its CollegeFootballData name",
    )
    @app_commands.describe(
        source_team="Team name as it appears from The Odds API (e.g. 'Texas Longhorns')",
        canonical_team="Team name as it appears from CollegeFootballData (e.g. 'Texas')",
    )
    async def add_alias(
        self, interaction: discord.Interaction, source_team: str, canonical_team: str
    ):
        team_aliases.add_alias(
            self.bot.conn, team_aliases.ODDS_API_SOURCE, source_team, canonical_team
        )
        await interaction.response.send_message(
            f"Mapped '{source_team}' -> '{canonical_team}'.", ephemeral=True
        )

    @app_commands.command(
        name="lock-check",
        description="Lock submitted parlays past kickoff and expire stale drafts",
    )
    async def lock_check_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await scheduler_jobs.lock_check_job(self.bot)
        await interaction.followup.send(
            f"Locked {len(result['locked'])} parlay(s), "
            f"expired {len(result['expired_drafts'])} stale draft(s).",
            ephemeral=True,
        )

    @app_commands.command(
        name="grade-week",
        description="Grade completed games, credit balances, and settle the weekly winner",
    )
    async def grade_week_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        week = repository.get_latest_week(self.bot.conn)
        if week is None:
            await interaction.followup.send("No week is open yet.", ephemeral=True)
            return

        # any winner announcement is posted to ADMIN_LOG_CHANNEL_ID (same as the
        # scheduled version of this job), not necessarily this interaction's channel
        result = await scheduler_jobs.grade_week_job(self.bot)

        summary = f"Graded {len(result['graded'])} parlay(s)."
        if result["skipped_incomplete"]:
            summary += (
                f" {len(result['skipped_incomplete'])} parlay(s) still waiting on final scores."
            )
        await interaction.followup.send(summary, ephemeral=True)

    @app_commands.command(
        name="usage-report", description="Show this month's CFBD/Odds API usage"
    )
    async def usage_report(self, interaction: discord.Interaction):
        rows = repository.get_monthly_api_usage(self.bot.conn)
        if not rows:
            await interaction.response.send_message(
                "No API usage recorded yet this month.", ephemeral=True
            )
            return

        lines = ["API usage this month:"]
        for row in rows:
            lines.append(f"- {row['service']}: {row['total_credits']} credits ({row['calls']} calls)")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(
        name="sync-teams",
        description="Cache team logos from CollegeFootballData (run once per season, not weekly)",
    )
    async def sync_teams(self, interaction: discord.Interaction):
        await handle_sync_teams(interaction)

    @app_commands.command(
        name="test-seed",
        description="[TEST] Create a synthetic test week - no waiting on real games/odds",
    )
    async def test_seed(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        existing = _get_test_week(self.bot)
        if existing:
            repository.delete_week_cascade(self.bot.conn, existing["id"])

        week_id = repository.upsert_week(
            self.bot.conn, TEST_SEASON_YEAR, TEST_WEEK_NUMBER, TEST_SEASON_TYPE
        )
        now = timeutils.utc_now()
        games = [
            CfbdGame(
                cfbd_game_id=cfbd_id,
                home_team=home,
                away_team=away,
                start_time_utc=(now + timedelta(minutes=offset)).isoformat(),
                status="scheduled",
                home_score=None,
                away_score=None,
            )
            for cfbd_id, home, away, offset in TEST_GAMES
        ]
        repository.upsert_games(self.bot.conn, week_id, games)

        for _, home, away, _ in TEST_GAMES:
            game, _ = repository.find_game_by_teams(self.bot.conn, week_id, home, away)
            event = OddsEvent(
                home_team_raw=home, away_team_raw=away, commence_time=game["start_time_utc"], book="test",
                spread_home=-6.5, spread_price_home=-110, spread_price_away=-110,
                moneyline_home=-250, moneyline_away=200,
                total_points=52.5, over_price=-110, under_price=-110,
            )
            repository.insert_odds_snapshot(self.bot.conn, game["id"], event, flipped=False)

        repository.replace_rankings(
            self.bot.conn, week_id, [RankedTeam(rank=r, school=s) for r, s in TEST_RANKINGS]
        )

        await interaction.followup.send(
            f"Seeded a test week with {len(TEST_GAMES)} games (some kick off in minutes, "
            "some in hours/a day) and Top 25 rankings - it's now the latest week, so /board, "
            "/optin, /parlay start, etc. all use it. Once you've placed some bets, run "
            "/admin test-finish-week to auto-finish every remaining game with random scores and "
            "grade the whole week in one shot. Run /admin test-teardown when you're done.",
            ephemeral=True,
        )
        await status_panel.refresh(self.bot)

    @app_commands.command(
        name="test-finish-week",
        description="[TEST] Auto-finish every unfinished test-week game with random scores, then grade the week",
    )
    async def test_finish_week(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        week = _get_test_week(self.bot)
        if week is None:
            await interaction.followup.send(
                "No test week found - run /admin test-seed first.", ephemeral=True
            )
            return

        unfinished = [
            g for g in repository.list_games(self.bot.conn, week["id"]) if g["status"] != "final"
        ]
        for game in unfinished:
            home_score, away_score = _random_final_score()
            repository.set_game_final_score(self.bot.conn, game["id"], home_score, away_score)

        await scheduler_jobs.lock_check_job(self.bot)
        result = await scheduler_jobs.grade_week_job(self.bot)

        await interaction.followup.send(
            f"Finished {len(unfinished)} game(s) with random scores. Graded "
            f"{len(result['graded'])} parlay(s); {len(result['skipped_incomplete'])} still waiting "
            "on other games.",
            ephemeral=True,
        )

    @app_commands.command(
        name="test-teardown", description="[TEST] Delete the synthetic test week and everything under it"
    )
    async def test_teardown(self, interaction: discord.Interaction):
        week = _get_test_week(self.bot)
        if week is None:
            await interaction.response.send_message(
                "No test week found - nothing to tear down.", ephemeral=True
            )
            return
        removed = repository.delete_week_cascade(self.bot.conn, week["id"])
        await interaction.response.send_message(
            f"Test week removed ({removed} games deleted along with it).", ephemeral=True
        )
        await status_panel.refresh(self.bot)

    @app_commands.command(
        name="refresh-panel", description="Manually repost the week status panel"
    )
    async def refresh_panel_cmd(self, interaction: discord.Interaction):
        await handle_refresh_panel(interaction)

    @app_commands.command(
        name="refresh-scores",
        description="Pull the latest scores from CollegeFootballData and grade anything that just finished",
    )
    async def refresh_scores_cmd(self, interaction: discord.Interaction):
        await handle_refresh_scores(interaction)

    @app_commands.command(
        name="reset-week",
        description="[Tenenbaum/Ticcow only] Clear everyone's opt-ins and parlays for the current week",
    )
    async def reset_week_cmd(self, interaction: discord.Interaction):
        await handle_reset_week(interaction)

    @app_commands.command(
        name="add-roast",
        description="Add a line to the bot's roast pool - use {user} for the @mention",
    )
    @app_commands.describe(
        roast="The line, e.g. '{user} bets like a raccoon in a casino'. {balance} and {bet} also work",
        category="When it can come up (default: any time)",
    )
    @app_commands.choices(
        category=[
            app_commands.Choice(name=label, value=key)
            for key, (_, label, _) in zingers.ROAST_CATEGORIES.items()
        ]
    )
    async def add_roast_cmd(
        self, interaction: discord.Interaction, roast: str, category: app_commands.Choice[str] | None = None
    ):
        await handle_add_roast(interaction, category.value if category else "generic", roast)

    @app_commands.command(name="list-roasts", description="Show the roasts added with /admin add-roast")
    async def list_roasts_cmd(self, interaction: discord.Interaction):
        rows = repository.list_custom_roasts(self.bot.conn)
        if not rows:
            await interaction.response.send_message(
                "No custom roasts yet - add one with /admin add-roast.", ephemeral=True
            )
            return
        lines = [
            f"#{row['id']} ({zingers.ROAST_CATEGORIES[row['category']][1]}, added by <@{row['added_by']}>): "
            f"{row['template']}"
            for row in rows
        ]
        message = "\n".join(lines)
        if len(message) > 1900:
            message = message[:1900].rsplit("\n", 1)[0] + "\n...and more"
        await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(
        name="remove-roast", description="[Tenenbaum/Ticcow only] Remove a roast added with /admin add-roast"
    )
    @app_commands.describe(roast="Which roast to remove")
    async def remove_roast_cmd(self, interaction: discord.Interaction, roast: int):
        if interaction.user.id not in TRUSTED_ADMIN_USER_IDS:
            await interaction.response.send_message("Only Tenenbaum or Ticcow can remove roasts.", ephemeral=True)
            return
        if repository.remove_custom_roast(self.bot.conn, roast):
            await interaction.response.send_message(f"Removed roast #{roast}.", ephemeral=True)
        else:
            await interaction.response.send_message(f"There's no custom roast #{roast}.", ephemeral=True)

    @remove_roast_cmd.autocomplete("roast")
    async def remove_roast_autocomplete(self, interaction: discord.Interaction, current: str):
        rows = repository.list_custom_roasts(self.bot.conn)
        return [
            app_commands.Choice(name=f"#{row['id']}: {row['template']}"[:100], value=row["id"])
            for row in rows
            if current.lower() in row["template"].lower() or current == str(row["id"])
        ][:25]

    @app_commands.command(
        name="cleanup-channel",
        description="Manually delete stale duplicate panel posts older than 5 min (never chat or other bot posts)",
    )
    async def cleanup_channel_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        removed = await status_panel.cleanup_channel(self.bot)
        await interaction.followup.send(f"Removed {removed} message(s).", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
