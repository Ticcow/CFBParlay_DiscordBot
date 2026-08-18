import discord
from discord import app_commands
from discord.ext import commands

from bot.parlays import repository

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


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
