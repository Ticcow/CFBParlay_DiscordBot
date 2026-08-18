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
            await interaction.response.send_message("\n".join(lines))
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
        await interaction.response.send_message("\n".join(lines))

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
        await interaction.response.send_message("\n".join(lines))

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
