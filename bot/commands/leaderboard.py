import discord
from discord import app_commands
from discord.ext import commands

from bot.parlays import formatting, repository

MAX_PARLAY_FIELDS = 20


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

        parlays = [
            p
            for p in repository.list_submitted_parlays_for_week(self.bot.conn, week["id"])
            if user is None or p["user_id"] == user.id
        ]
        if not parlays:
            await interaction.response.send_message("No submitted parlays yet.", ephemeral=True)
            return

        embed = discord.Embed(title=f"Week {week['week_number']} Parlays")
        for parlay in parlays[:MAX_PARLAY_FIELDS]:
            legs = repository.list_legs_with_games(self.bot.conn, parlay["id"])
            leg_text = "\n".join(formatting.format_leg(leg) for leg in legs)
            wager = (
                f"${parlay['wager_dollars']:.2f}" if parlay["wager_dollars"] is not None else "-"
            )
            payout_text, status_label = formatting.format_payout_and_status(parlay)
            embed.add_field(
                name=f"<@{parlay['user_id']}> — #{parlay['id']} [{status_label}] "
                f"{wager} wager → {payout_text}",
                value=leg_text[:1024],
                inline=False,
            )
        if len(parlays) > MAX_PARLAY_FIELDS:
            embed.add_field(
                name="...",
                value=f"+{len(parlays) - MAX_PARLAY_FIELDS} more parlay(s) not shown",
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="leaderboard", description="View the weekly or season leaderboard")
    @app_commands.describe(scope="Which leaderboard to show")
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="This week", value="week"),
            app_commands.Choice(name="Season - most weekly wins", value="season-wins"),
            app_commands.Choice(name="Season - most money won", value="season-money"),
        ]
    )
    async def leaderboard(
        self, interaction: discord.Interaction, scope: app_commands.Choice[str] | None = None
    ):
        scope_value = scope.value if scope else "week"

        if scope_value == "week":
            week = repository.get_latest_week(self.bot.conn)
            if week is None:
                await interaction.response.send_message("No week is open yet.", ephemeral=True)
                return
            rows = repository.list_week_standings(self.bot.conn, week["id"])
            if not rows:
                await interaction.response.send_message(
                    "Nobody has opted in this week yet.", ephemeral=True
                )
                return
            lines = [f"Week {week['week_number']} standings:"]
            for i, row in enumerate(rows, start=1):
                crown = " 🏆" if row["is_weekly_winner"] else ""
                lines.append(f"{i}. <@{row['user_id']}> — ${row['current_balance']:.2f}{crown}")
            await interaction.response.send_message("\n".join(lines), ephemeral=True)
            return

        if scope_value == "season-wins":
            rows = repository.season_wins_leaderboard(self.bot.conn)
            lines = ["Season leaderboard - most weekly wins:"] + [
                f"{i}. <@{row['user_id']}> — {row['wins']} week(s) won"
                for i, row in enumerate(rows, start=1)
            ]
        else:
            rows = repository.season_money_leaderboard(self.bot.conn)
            lines = ["Season leaderboard - most money won:"] + [
                f"{i}. <@{row['user_id']}> — ${row['net']:.2f} net"
                for i, row in enumerate(rows, start=1)
            ]

        if not rows:
            await interaction.response.send_message("No season data yet.", ephemeral=True)
            return
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(name="mystats", description="View your season record")
    async def mystats(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        weekly_wins = repository.get_user_weekly_win_count(self.bot.conn, user_id)
        net = repository.get_user_season_net(self.bot.conn, user_id)
        record = repository.get_user_parlay_record(self.bot.conn, user_id)

        lines = [
            f"Weekly wins: {weekly_wins}",
            f"Season net winnings: ${net:.2f}",
            f"Parlay record: {record.get('win', 0)}-{record.get('loss', 0)}-{record.get('push', 0)} (W-L-P)",
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(name="history", description="View a past week's standings")
    @app_commands.describe(week="Which week")
    async def history(self, interaction: discord.Interaction, week: str):
        try:
            week_id = int(week)
        except ValueError:
            await interaction.response.send_message(
                "Pick a week from the autocomplete list.", ephemeral=True
            )
            return

        week_row = repository.get_week(self.bot.conn, week_id)
        if week_row is None:
            await interaction.response.send_message("No such week.", ephemeral=True)
            return

        rows = repository.list_week_standings(self.bot.conn, week_id)
        lines = [f"Week {week_row['week_number']} ({week_row['season_year']}) standings:"]
        if not rows:
            lines.append("(nobody opted in)")
        for i, row in enumerate(rows, start=1):
            crown = " 🏆" if row["is_weekly_winner"] else ""
            lines.append(f"{i}. <@{row['user_id']}> — ${row['current_balance']:.2f}{crown}")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @history.autocomplete("week")
    async def history_week_autocomplete(self, interaction: discord.Interaction, current: str):
        weeks = repository.list_all_weeks(self.bot.conn)
        return [
            app_commands.Choice(
                name=f"Week {w['week_number']} ({w['season_year']})", value=str(w["id"])
            )
            for w in weeks
        ][:25]


async def setup(bot: commands.Bot):
    await bot.add_cog(LeaderboardCog(bot))
