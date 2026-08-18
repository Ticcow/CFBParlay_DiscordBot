import random
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from bot.commands import status_panel
from bot.integrations import team_aliases
from bot.integrations.cfbd_client import CfbdGame, RankedTeam
from bot.integrations.odds_client import OddsEvent
from bot.parlays import repository, timeutils
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


@app_commands.default_permissions(manage_guild=True)
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
        await interaction.response.defer(ephemeral=True)

        if year is None and week is None:
            week_id = await scheduler_jobs.sync_week_games(self.bot)
            if week_id is None:
                await interaction.followup.send(
                    "No current CFBD week found - probably off-season, or CFBD hasn't "
                    "published this year's calendar yet. Use year/week to force a specific one.",
                    ephemeral=True,
                )
                return
            week_row = repository.get_week(self.bot.conn, week_id)
            games = repository.list_games(self.bot.conn, week_id)
            await interaction.followup.send(
                f"Synced Week {week_row['week_number']} ({week_row['season_type']}, "
                f"{week_row['season_year']}) - {len(games)} games.",
                ephemeral=True,
            )
            return

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
        await interaction.response.defer(ephemeral=True)
        week = repository.get_latest_week(self.bot.conn)
        if week is None:
            await interaction.followup.send(
                "No week has been synced yet - run /admin sync-week first.", ephemeral=True
            )
            return

        events = await self.bot.odds.get_ncaaf_odds()
        result = repository.sync_odds_for_week(self.bot.conn, week["id"], events)

        message = f"Matched odds for {result.matched} game(s)."
        if result.unmatched:
            unmatched_list = "\n".join(
                f"- {away} @ {home}" for home, away in result.unmatched
            )
            message += (
                f"\n\n{len(result.unmatched)} event(s) couldn't be matched to a synced game "
                f"(team name mismatch). Use /admin add-alias to map them:\n{unmatched_list}"
            )
        await interaction.followup.send(message, ephemeral=True)

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
        await interaction.response.defer(ephemeral=True)
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
        await interaction.response.defer(ephemeral=True)
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
        await interaction.response.defer(ephemeral=True)
        year = season.season_year_for(timeutils.utc_now())
        teams = await self.bot.cfbd.get_teams(year)
        repository.upsert_team_logos(self.bot.conn, teams)
        await interaction.followup.send(f"Cached logos for {len(teams)} teams.", ephemeral=True)

    @app_commands.command(
        name="test-seed",
        description="[TEST] Create a synthetic test week - no waiting on real games/odds",
    )
    async def test_seed(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
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
            "grade the whole week in one shot (or /admin test-finish-game to control one game's "
            "score yourself). Run /admin test-teardown when you're done.",
            ephemeral=True,
        )
        await status_panel.refresh(self.bot)

    @app_commands.command(
        name="test-finish-game",
        description="[TEST] Force a test-week game to final with a specific score, to test grading on demand",
    )
    @app_commands.describe(
        game="Which game", home_score="Home team's final score", away_score="Away team's final score"
    )
    async def test_finish_game(
        self, interaction: discord.Interaction, game: str, home_score: int, away_score: int
    ):
        week = _get_test_week(self.bot)
        if week is None:
            await interaction.response.send_message(
                "No test week found - run /admin test-seed first.", ephemeral=True
            )
            return
        try:
            game_id = int(game)
        except ValueError:
            await interaction.response.send_message(
                "Pick a game from the autocomplete list.", ephemeral=True
            )
            return
        game_row = repository.get_game(self.bot.conn, game_id)
        if game_row is None or game_row["week_id"] != week["id"]:
            await interaction.response.send_message(
                "That game isn't part of the test week - this command only touches test data.",
                ephemeral=True,
            )
            return
        repository.set_game_final_score(self.bot.conn, game_id, home_score, away_score)
        await interaction.response.send_message(
            f"Marked game final: {away_score}-{home_score}. Run /admin grade-week to grade it.",
            ephemeral=True,
        )

    @test_finish_game.autocomplete("game")
    async def test_finish_game_autocomplete(self, interaction: discord.Interaction, current: str):
        week = _get_test_week(self.bot)
        if week is None:
            return []
        games = repository.search_games(self.bot.conn, week["id"], current, limit=25)
        return [
            app_commands.Choice(
                name=f"{g['away_team']} @ {g['home_team']} [{g['status']}]"[:100], value=str(g["id"])
            )
            for g in games
        ]

    @app_commands.command(
        name="test-finish-week",
        description="[TEST] Auto-finish every unfinished test-week game with random scores, then grade the week",
    )
    async def test_finish_week(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
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
        await status_panel.refresh(self.bot)
        await interaction.response.send_message("Panel refreshed.", ephemeral=True)

    @app_commands.command(
        name="cleanup-channel",
        description="Manually delete anything older than 5 min in the panel channel except the panel",
    )
    async def cleanup_channel_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        removed = await status_panel.cleanup_channel(self.bot)
        await interaction.followup.send(f"Removed {removed} message(s).", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
