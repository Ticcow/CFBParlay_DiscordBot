import discord
from discord import app_commands
from discord.ext import commands

from bot.parlays import formatting, repository


class LeaderboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="parlays", description="View submitted parlays for this week")
    @app_commands.describe(user="Only show this user's parlays")
    async def parlays(self, interaction: discord.Interaction, user: discord.User | None = None):
        week = repository.get_latest_week(self.bot.conn)
        if week is None:
            await interaction.response.send_message("No week is open yet.", ephemeral=True)
            return

        visible = repository.week_is_visible(self.bot.conn, week["id"])

        if user is not None and user.id != interaction.user.id and not visible:
            await interaction.response.send_message(
                "Other members' parlays stay hidden until the week's first game kicks off.",
                ephemeral=True,
            )
            return

        if not visible:
            parlays = [
                p
                for p in repository.list_parlays_for_user_week(
                    self.bot.conn, interaction.user.id, week["id"]
                )
                if p["status"] != "draft"
            ]
            header = "Your submitted parlays this week (everyone else's stay hidden until kickoff):"
        else:
            parlays = [
                p
                for p in repository.list_submitted_parlays_for_week(self.bot.conn, week["id"])
                if user is None or p["user_id"] == user.id
            ]
            header = "This week's submitted parlays:"

        if not parlays:
            await interaction.response.send_message("No submitted parlays yet.", ephemeral=True)
            return

        lines = [header]
        for parlay in parlays:
            legs = repository.list_legs_with_games(self.bot.conn, parlay["id"])
            leg_text = "; ".join(formatting.format_leg(leg) for leg in legs)
            wager = (
                f"${parlay['wager_dollars']:.2f}" if parlay["wager_dollars"] is not None else "-"
            )
            lines.append(
                f"<@{parlay['user_id']}> — #{parlay['id']} [{parlay['status']}] {wager}: {leg_text}"
            )

        await interaction.response.send_message("\n".join(lines), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(LeaderboardCog(bot))
