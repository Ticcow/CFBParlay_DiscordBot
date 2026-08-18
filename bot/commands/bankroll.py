import discord
from discord import app_commands
from discord.ext import commands

from bot.commands import status_panel
from bot.parlays import repository


class BankrollCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="optin", description="Join this week's competition with a $1,000 bankroll"
    )
    async def optin(self, interaction: discord.Interaction):
        week = repository.get_latest_week(self.bot.conn)
        if week is None:
            await interaction.response.send_message("No week is open yet.", ephemeral=True)
            return

        if repository.get_participant(self.bot.conn, interaction.user.id, week["id"]):
            await interaction.response.send_message(
                "You're already opted in for this week.", ephemeral=True
            )
            return

        repository.opt_in(self.bot.conn, interaction.user.id, week["id"])
        await interaction.response.send_message(
            f"You're in for Week {week['week_number']}! Starting bankroll: $1,000.00",
            ephemeral=True,
        )
        await status_panel.refresh(self.bot)

    @app_commands.command(
        name="balance", description="Show your current-week bankroll and parlays"
    )
    async def balance(self, interaction: discord.Interaction):
        week = repository.get_latest_week(self.bot.conn)
        if week is None:
            await interaction.response.send_message("No week is open yet.", ephemeral=True)
            return

        participant = repository.get_participant(self.bot.conn, interaction.user.id, week["id"])
        if participant is None:
            await interaction.response.send_message(
                "You haven't opted in this week - run /optin first.", ephemeral=True
            )
            return

        lines = [
            f"Balance: ${participant['current_balance']:.2f} "
            f"(started at ${participant['starting_balance']:.2f})"
        ]
        parlays = repository.list_parlays_for_user_week(
            self.bot.conn, interaction.user.id, week["id"]
        )
        if parlays:
            lines.append("")
            lines.append("Parlays this week:")
            for parlay in parlays:
                wager = (
                    f"${parlay['wager_dollars']:.2f}"
                    if parlay["wager_dollars"] is not None
                    else "-"
                )
                lines.append(f"- #{parlay['id']} [{parlay['status']}] wager {wager}")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(BankrollCog(bot))
