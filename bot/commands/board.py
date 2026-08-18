import discord
from discord import app_commands
from discord.ext import commands

from bot.parlays import repository


class BoardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="board", description="Show this week's games and cached lines"
    )
    async def board(self, interaction: discord.Interaction):
        week = repository.get_latest_week(self.bot.conn)
        if week is None:
            await interaction.response.send_message(
                "No week has been synced yet.", ephemeral=True
            )
            return

        games = repository.list_games(self.bot.conn, week["id"])
        if not games:
            await interaction.response.send_message(
                f"Week {week['week_number']}, {week['season_year']} has no games synced.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(title=f"Week {week['week_number']} ({week['season_year']})")
        for game in games:
            score = ""
            if game["status"] == "final":
                score = f" — final {game['away_score']}-{game['home_score']}"
            embed.add_field(
                name=f"{game['away_team']} @ {game['home_team']}",
                value=f"{game['start_time_utc']}{score}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(BoardCog(bot))
