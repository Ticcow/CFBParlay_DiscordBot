import discord
from discord import app_commands
from discord.ext import commands

from bot.integrations import team_aliases
from bot.parlays import repository
from bot.scheduler import jobs as scheduler_jobs

SEASON_TYPE_CHOICES = [
    app_commands.Choice(name="regular", value="regular"),
    app_commands.Choice(name="postseason", value="postseason"),
]


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


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
