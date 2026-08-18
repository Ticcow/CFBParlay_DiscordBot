import discord
from discord import app_commands
from discord.ext import commands

from bot.commands import parlay_views
from bot.parlays import repository


class ParlayCog(commands.GroupCog, name="parlay"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()

    @app_commands.command(
        name="start", description="Start (or resume) building this week's parlay - fully click-through"
    )
    async def start(self, interaction: discord.Interaction):
        week = repository.get_latest_week(self.bot.conn)
        if week is None:
            await interaction.response.send_message("No week is open yet.", ephemeral=True)
            return
        if repository.get_participant(self.bot.conn, interaction.user.id, week["id"]) is None:
            await interaction.response.send_message("Opt in first with /optin.", ephemeral=True)
            return

        parlay = repository.get_draft_parlay(self.bot.conn, interaction.user.id, week["id"])
        parlay_id = (
            parlay["id"]
            if parlay
            else repository.start_parlay(self.bot.conn, interaction.user.id, week["id"])
        )

        embed, view = parlay_views.render_panel(self.bot, parlay_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="view", description="View (and resume building) your current draft parlay")
    async def view(self, interaction: discord.Interaction):
        week = repository.get_latest_week(self.bot.conn)
        parlay = week and repository.get_draft_parlay(self.bot.conn, interaction.user.id, week["id"])
        if parlay is None:
            await interaction.response.send_message(
                "You don't have a draft parlay - start one with /parlay start.", ephemeral=True
            )
            return
        embed, view = parlay_views.render_panel(self.bot, parlay["id"])
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="cancel", description="Cancel your draft parlay")
    async def cancel(self, interaction: discord.Interaction):
        week = repository.get_latest_week(self.bot.conn)
        parlay = week and repository.get_draft_parlay(self.bot.conn, interaction.user.id, week["id"])
        if parlay is None:
            await interaction.response.send_message("You don't have a draft parlay.", ephemeral=True)
            return
        repository.cancel_parlay(self.bot.conn, parlay["id"])
        await interaction.response.send_message("Draft parlay cancelled.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ParlayCog(bot))
