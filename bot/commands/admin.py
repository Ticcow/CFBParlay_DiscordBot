import discord
from discord import app_commands
from discord.ext import commands

from bot.integrations import team_aliases
from bot.parlays import grading, locking, repository, standings

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
        name="sync-week", description="Pull a week's games from CollegeFootballData"
    )
    @app_commands.describe(
        year="Season year, e.g. 2026",
        week="Week number",
        season_type="regular or postseason",
    )
    @app_commands.choices(season_type=SEASON_TYPE_CHOICES)
    async def sync_week(
        self,
        interaction: discord.Interaction,
        year: int,
        week: int,
        season_type: app_commands.Choice[str] | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
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
        result = locking.lock_check(self.bot.conn)

        for user_id, parlay_id in result["expired_drafts"]:
            try:
                user = await self.bot.fetch_user(user_id)
                await user.send(
                    f"Your draft parlay #{parlay_id} was cancelled - one of its games "
                    "kicked off before you submitted."
                )
            except discord.HTTPException:
                pass  # best-effort DM; a closed DM or unknown user shouldn't fail the job

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

        result = grading.grade_week(self.bot.conn, week["id"])
        winners = standings.finalize_week(self.bot.conn, week["id"])

        summary = f"Graded {len(result['graded'])} parlay(s)."
        if result["skipped_incomplete"]:
            summary += (
                f" {len(result['skipped_incomplete'])} parlay(s) still waiting on final scores."
            )
        await interaction.followup.send(summary, ephemeral=True)

        if winners:
            standings_rows = repository.list_week_standings(self.bot.conn, week["id"])
            lines = [f"🏆 Week {week['week_number']} is final!"]
            for i, row in enumerate(standings_rows, start=1):
                crown = " 🏆" if row["is_weekly_winner"] else ""
                lines.append(f"{i}. <@{row['user_id']}> — ${row['current_balance']:.2f}{crown}")
            await interaction.channel.send("\n".join(lines))


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
