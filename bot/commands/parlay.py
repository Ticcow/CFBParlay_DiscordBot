import discord
from discord import app_commands
from discord.ext import commands

from bot.parlays import formatting, payout, repository, timeutils

MARKET_CHOICES = [
    app_commands.Choice(name="Spread", value="spread"),
    app_commands.Choice(name="Moneyline", value="moneyline"),
    app_commands.Choice(name="Total", value="total"),
]

MIN_LEGS = 3
MAX_LEGS = 6


def _selection_choices(game, snapshot, market: str) -> list[app_commands.Choice]:
    if snapshot is None:
        return []

    choices = []
    if market == "spread" and snapshot["spread_home"] is not None:
        away_spread = -snapshot["spread_home"]
        choices.append(
            app_commands.Choice(
                name=f"{game['home_team']} {snapshot['spread_home']:+g} "
                f"({formatting.format_price(snapshot['spread_price_home'])})",
                value="home",
            )
        )
        choices.append(
            app_commands.Choice(
                name=f"{game['away_team']} {away_spread:+g} "
                f"({formatting.format_price(snapshot['spread_price_away'])})",
                value="away",
            )
        )
    elif market == "moneyline" and snapshot["moneyline_home"] is not None:
        choices.append(
            app_commands.Choice(
                name=f"{game['home_team']} ({formatting.format_price(snapshot['moneyline_home'])})",
                value="home",
            )
        )
        choices.append(
            app_commands.Choice(
                name=f"{game['away_team']} ({formatting.format_price(snapshot['moneyline_away'])})",
                value="away",
            )
        )
    elif market == "total" and snapshot["total_points"] is not None:
        choices.append(
            app_commands.Choice(
                name=f"Over {snapshot['total_points']:g} ({formatting.format_price(snapshot['over_price'])})",
                value="over",
            )
        )
        choices.append(
            app_commands.Choice(
                name=f"Under {snapshot['total_points']:g} ({formatting.format_price(snapshot['under_price'])})",
                value="under",
            )
        )
    return choices


def _resolve_selection(snapshot, market: str, selection: str):
    """Returns (line_value, price_american), or (None, None) if unavailable."""
    if market == "spread":
        if selection == "home":
            return snapshot["spread_home"], snapshot["spread_price_home"]
        if selection == "away":
            home_spread = snapshot["spread_home"]
            away_spread = -home_spread if home_spread is not None else None
            return away_spread, snapshot["spread_price_away"]
    elif market == "moneyline":
        if selection == "home":
            return None, snapshot["moneyline_home"]
        if selection == "away":
            return None, snapshot["moneyline_away"]
    elif market == "total":
        if selection == "over":
            return snapshot["total_points"], snapshot["over_price"]
        if selection == "under":
            return snapshot["total_points"], snapshot["under_price"]
    return None, None


class ConfirmSubmitView(discord.ui.View):
    def __init__(self, bot, parlay_id, participant_id, wager, potential, owner_id):
        super().__init__(timeout=60)
        self.bot = bot
        self.parlay_id = parlay_id
        self.participant_id = participant_id
        self.wager = wager
        self.potential = potential
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This isn't your confirmation.", ephemeral=True
            )
            return False
        return True

    def _disable(self):
        for child in self.children:
            child.disabled = True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button):
        ok = repository.submit_parlay(
            self.bot.conn, self.parlay_id, self.participant_id, self.wager, self.potential
        )
        self._disable()
        if not ok:
            await interaction.response.edit_message(
                content="Submit failed - your balance changed since you started this. Try again.",
                view=self,
            )
            return
        await interaction.response.edit_message(
            content=(
                f"Parlay #{self.parlay_id} submitted! Wager ${self.wager:.2f}, "
                f"potential payout ${self.potential:.2f}."
            ),
            view=self,
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button):
        self._disable()
        await interaction.response.edit_message(
            content="Submit cancelled - your parlay is still in draft.", view=self
        )


class ParlayCog(commands.GroupCog, name="parlay"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()

    @app_commands.command(name="start", description="Start building a new parlay for this week")
    async def start(self, interaction: discord.Interaction):
        week = repository.get_latest_week(self.bot.conn)
        if week is None:
            await interaction.response.send_message("No week is open yet.", ephemeral=True)
            return
        if repository.get_participant(self.bot.conn, interaction.user.id, week["id"]) is None:
            await interaction.response.send_message(
                "Opt in first with /optin.", ephemeral=True
            )
            return
        if repository.get_draft_parlay(self.bot.conn, interaction.user.id, week["id"]):
            await interaction.response.send_message(
                "You already have a draft parlay in progress - use /parlay view, "
                "/parlay submit, or /parlay cancel.",
                ephemeral=True,
            )
            return

        repository.start_parlay(self.bot.conn, interaction.user.id, week["id"])
        await interaction.response.send_message(
            f"Started a new parlay. Add {MIN_LEGS}-{MAX_LEGS} legs with /parlay add-leg.",
            ephemeral=True,
        )

    @app_commands.command(name="add-leg", description="Add a leg to your draft parlay")
    @app_commands.describe(game="Game", market="Bet type", selection="Your pick")
    @app_commands.choices(market=MARKET_CHOICES)
    async def add_leg(
        self,
        interaction: discord.Interaction,
        game: str,
        market: app_commands.Choice[str],
        selection: str,
    ):
        week = repository.get_latest_week(self.bot.conn)
        parlay = week and repository.get_draft_parlay(self.bot.conn, interaction.user.id, week["id"])
        if parlay is None:
            await interaction.response.send_message(
                "Start a parlay first with /parlay start.", ephemeral=True
            )
            return

        try:
            game_id = int(game)
        except ValueError:
            await interaction.response.send_message(
                "Pick a game from the autocomplete list.", ephemeral=True
            )
            return

        game_row = repository.get_game(self.bot.conn, game_id)
        if game_row is None or game_row["week_id"] != week["id"]:
            await interaction.response.send_message("That game isn't part of this week.", ephemeral=True)
            return
        if timeutils.parse_utc(game_row["start_time_utc"]) <= timeutils.utc_now():
            await interaction.response.send_message("That game has already started.", ephemeral=True)
            return

        existing_legs = repository.list_legs(self.bot.conn, parlay["id"])
        if len(existing_legs) >= MAX_LEGS:
            await interaction.response.send_message(
                f"A parlay can have at most {MAX_LEGS} legs.", ephemeral=True
            )
            return
        if any(leg["game_id"] == game_id for leg in existing_legs):
            await interaction.response.send_message(
                "That game is already in this parlay - no same-game legs.", ephemeral=True
            )
            return

        snapshot = repository.get_latest_odds_snapshot(self.bot.conn, game_id)
        if snapshot is None:
            await interaction.response.send_message(
                "No odds cached for that game yet.", ephemeral=True
            )
            return

        market_value = market.value
        line_value, price = _resolve_selection(snapshot, market_value, selection)
        if price is None:
            await interaction.response.send_message(
                "That selection isn't available for this game.", ephemeral=True
            )
            return

        leg_number = repository.add_leg(
            self.bot.conn,
            parlay["id"],
            game_id,
            snapshot["id"],
            market_value,
            selection,
            line_value,
            price,
        )
        await interaction.response.send_message(
            f"Added leg {leg_number}/{MAX_LEGS}. Use /parlay view to see your parlay so far.",
            ephemeral=True,
        )

    @add_leg.autocomplete("game")
    async def game_autocomplete(self, interaction: discord.Interaction, current: str):
        week = repository.get_latest_week(self.bot.conn)
        if week is None:
            return []
        now = timeutils.utc_now()
        options = []
        for g in repository.search_games(self.bot.conn, week["id"], current, limit=50):
            if timeutils.parse_utc(g["start_time_utc"]) <= now:
                continue
            options.append(
                app_commands.Choice(name=f"{g['away_team']} @ {g['home_team']}"[:100], value=str(g["id"]))
            )
            if len(options) >= 25:
                break
        return options

    @add_leg.autocomplete("selection")
    async def selection_autocomplete(self, interaction: discord.Interaction, current: str):
        game_value = getattr(interaction.namespace, "game", None)
        market_value = getattr(interaction.namespace, "market", None)
        if not game_value or not market_value:
            return []
        try:
            game_id = int(game_value)
        except ValueError:
            return []
        game_row = repository.get_game(self.bot.conn, game_id)
        if game_row is None:
            return []
        snapshot = repository.get_latest_odds_snapshot(self.bot.conn, game_id)
        return _selection_choices(game_row, snapshot, market_value)

    @app_commands.command(name="remove-leg", description="Remove a leg from your draft parlay")
    @app_commands.describe(leg_number="Which leg to remove")
    async def remove_leg(self, interaction: discord.Interaction, leg_number: int):
        week = repository.get_latest_week(self.bot.conn)
        parlay = week and repository.get_draft_parlay(self.bot.conn, interaction.user.id, week["id"])
        if parlay is None:
            await interaction.response.send_message("You don't have a draft parlay.", ephemeral=True)
            return
        if not repository.remove_leg(self.bot.conn, parlay["id"], leg_number):
            await interaction.response.send_message("No such leg.", ephemeral=True)
            return
        await interaction.response.send_message(f"Removed leg {leg_number}.", ephemeral=True)

    @remove_leg.autocomplete("leg_number")
    async def remove_leg_autocomplete(self, interaction: discord.Interaction, current: str):
        week = repository.get_latest_week(self.bot.conn)
        parlay = week and repository.get_draft_parlay(self.bot.conn, interaction.user.id, week["id"])
        if parlay is None:
            return []
        legs = repository.list_legs_with_games(self.bot.conn, parlay["id"])
        return [
            app_commands.Choice(name=formatting.format_leg(leg)[:100], value=leg["leg_number"])
            for leg in legs
        ][:25]

    @app_commands.command(name="view", description="View your current draft parlay")
    async def view(self, interaction: discord.Interaction):
        week = repository.get_latest_week(self.bot.conn)
        parlay = week and repository.get_draft_parlay(self.bot.conn, interaction.user.id, week["id"])
        if parlay is None:
            await interaction.response.send_message(
                "You don't have a draft parlay - start one with /parlay start.", ephemeral=True
            )
            return
        legs = repository.list_legs_with_games(self.bot.conn, parlay["id"])
        if not legs:
            await interaction.response.send_message("Your draft parlay has no legs yet.", ephemeral=True)
            return
        await interaction.response.send_message(
            "\n".join(formatting.format_leg(leg) for leg in legs), ephemeral=True
        )

    @app_commands.command(name="submit", description="Submit your draft parlay and lock in a wager")
    @app_commands.describe(wager="Dollar amount to wager (from your remaining bankroll)")
    async def submit(
        self, interaction: discord.Interaction, wager: app_commands.Range[float, 0.01, 1000.0]
    ):
        week = repository.get_latest_week(self.bot.conn)
        if week is None:
            await interaction.response.send_message("No week is open yet.", ephemeral=True)
            return
        participant = repository.get_participant(self.bot.conn, interaction.user.id, week["id"])
        if participant is None:
            await interaction.response.send_message("Opt in first with /optin.", ephemeral=True)
            return
        parlay = repository.get_draft_parlay(self.bot.conn, interaction.user.id, week["id"])
        if parlay is None:
            await interaction.response.send_message("You don't have a draft parlay.", ephemeral=True)
            return

        legs = repository.list_legs_with_games(self.bot.conn, parlay["id"])
        if len(legs) < MIN_LEGS:
            await interaction.response.send_message(
                f"A parlay needs at least {MIN_LEGS} legs (you have {len(legs)}).", ephemeral=True
            )
            return

        now = timeutils.utc_now()
        if any(timeutils.parse_utc(leg["start_time_utc"]) <= now for leg in legs):
            await interaction.response.send_message(
                "One or more of your legs has already started - remove it before submitting.",
                ephemeral=True,
            )
            return

        if wager > participant["current_balance"]:
            await interaction.response.send_message(
                f"You only have ${participant['current_balance']:.2f} left this week.", ephemeral=True
            )
            return

        potential = payout.potential_payout(wager, [leg["price_american"] for leg in legs])
        view = ConfirmSubmitView(self.bot, parlay["id"], participant["id"], wager, potential, interaction.user.id)
        leg_summary = "\n".join(formatting.format_leg(leg) for leg in legs)
        await interaction.response.send_message(
            f"{leg_summary}\n\n"
            f"Wager: ${wager:.2f}\n"
            f"Potential payout: ${potential:.2f}\n"
            f"Balance after: ${participant['current_balance'] - wager:.2f}\n\n"
            f"Confirm submission?",
            view=view,
            ephemeral=True,
        )

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
