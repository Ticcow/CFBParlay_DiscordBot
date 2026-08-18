import discord
from discord import app_commands
from discord.ext import commands

from bot.parlays import repository


def _format_price(price: int | None) -> str:
    if price is None:
        return "?"
    return f"+{price}" if price > 0 else str(price)


def _format_odds_line(snapshot) -> str:
    if snapshot is None:
        return "no lines cached yet"

    parts = []
    if snapshot["spread_home"] is not None:
        parts.append(
            f"spread {snapshot['spread_home']:+g} ({_format_price(snapshot['spread_price_home'])})"
        )
    if snapshot["total_points"] is not None:
        parts.append(f"O/U {snapshot['total_points']:g}")
    if snapshot["moneyline_home"] is not None:
        parts.append(f"ML {_format_price(snapshot['moneyline_home'])}")
    return " | ".join(parts) if parts else "no lines cached yet"


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
            snapshot = repository.get_latest_odds_snapshot(self.bot.conn, game["id"])
            embed.add_field(
                name=f"{game['away_team']} @ {game['home_team']}",
                value=f"{game['start_time_utc']}{score}\n{_format_odds_line(snapshot)}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(BoardCog(bot))
