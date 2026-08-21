from zoneinfo import ZoneInfo

import discord

from bot.commands import status_panel
from bot.parlays import formatting, payout, repository, selections, timeutils, zingers

MIN_LEGS = 3
MAX_LEGS = 6
PAGE_SIZE = 25
VIEW_TIMEOUT = 900  # 15 min - generous for a click-through build session

EASTERN = ZoneInfo("America/New_York")


def _kickoff_label(start_time_utc: str) -> str:
    dt = timeutils.parse_utc(start_time_utc).astimezone(EASTERN)
    time_str = dt.strftime("%I:%M %p").lstrip("0")
    return f"{dt.strftime('%a')} {time_str} ET"


def render_panel(bot, parlay_id: int) -> tuple[discord.Embed, "ParlayPanelView"]:
    """The 'home' screen: current legs plus Add/Remove/Submit/Cancel controls.
    Every other screen in this flow eventually edits back to this one."""
    parlay = repository.get_parlay(bot.conn, parlay_id)
    legs = repository.list_legs_with_games(bot.conn, parlay_id)

    embed = discord.Embed(title="🎰 Your parlay")
    embed.description = (
        "\n".join(formatting.format_leg(leg) for leg in legs)
        if legs
        else "No legs yet - tap **Add Leg** to get started."
    )
    embed.set_footer(text=f"{len(legs)}/{MAX_LEGS} legs (minimum {MIN_LEGS} to submit)")
    return embed, ParlayPanelView(bot, parlay_id, parlay["week_id"], len(legs))


class ParlayPanelView(discord.ui.View):
    def __init__(self, bot, parlay_id: int, week_id: int, leg_count: int):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.bot = bot
        self.parlay_id = parlay_id
        self.week_id = week_id
        self._build(leg_count)

    def _build(self, leg_count: int):
        self.clear_items()

        add_button = discord.ui.Button(
            label="➕ Add Leg", style=discord.ButtonStyle.success, disabled=leg_count >= MAX_LEGS
        )
        add_button.callback = self._on_add
        self.add_item(add_button)

        if leg_count:
            remove_button = discord.ui.Button(label="➖ Remove Leg", style=discord.ButtonStyle.secondary)
            remove_button.callback = self._on_remove
            self.add_item(remove_button)

        submit_button = discord.ui.Button(
            label="✅ Submit", style=discord.ButtonStyle.primary, disabled=leg_count < MIN_LEGS
        )
        submit_button.callback = self._on_submit
        self.add_item(submit_button)

        cancel_button = discord.ui.Button(label="❌ Cancel Parlay", style=discord.ButtonStyle.danger)
        cancel_button.callback = self._on_cancel
        self.add_item(cancel_button)

    async def _on_add(self, interaction: discord.Interaction):
        embed, view = _ranked_screen(self.bot, self.parlay_id, self.week_id)
        await interaction.response.edit_message(embed=embed, view=view)

    async def _on_remove(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Remove a leg", description="Pick which leg to remove.")
        view = RemoveLegView(self.bot, self.parlay_id)
        await interaction.response.edit_message(embed=embed, view=view)

    async def _on_submit(self, interaction: discord.Interaction):
        parlay = repository.get_parlay(self.bot.conn, self.parlay_id)
        participant = repository.get_participant(self.bot.conn, parlay["user_id"], parlay["week_id"])
        legs = repository.list_legs_with_games(self.bot.conn, self.parlay_id)

        now = timeutils.utc_now()
        if any(timeutils.parse_utc(leg["start_time_utc"]) <= now for leg in legs):
            embed = discord.Embed(
                title="Can't submit yet",
                description="One or more of your legs has already started - remove it first.",
            )
            await interaction.response.edit_message(embed=embed, view=self)
            return

        embed, view = _wager_screen(self.bot, self.parlay_id, participant)
        await interaction.response.edit_message(embed=embed, view=view)

    async def _on_cancel(self, interaction: discord.Interaction):
        repository.cancel_parlay(self.bot.conn, self.parlay_id)
        embed = discord.Embed(
            title="Parlay cancelled", description="Start a new one anytime with /parlay start."
        )
        await interaction.response.edit_message(embed=embed, view=None)


def _team_label(team: str, rank: int | None) -> str:
    return f"#{rank} {team}" if rank is not None else team


def _matchup_label(home_rank: int | None, away_rank: int | None, game) -> str:
    return f"{_team_label(game['away_team'], away_rank)} vs {_team_label(game['home_team'], home_rank)}"


def _format_ranked_list(ranked_games: list[tuple[int, int | None, int | None, object]]) -> str:
    if not ranked_games:
        return "No ranked teams have an available game this week."
    return "\n".join(
        f"**{_matchup_label(home_rank, away_rank, game)}** — {_kickoff_label(game['start_time_utc'])}"
        for _sort_rank, home_rank, away_rank, game in ranked_games
    )


def _ranked_screen(bot, parlay_id: int, week_id: int) -> tuple[discord.Embed, "RankedGamePickerView"]:
    now = timeutils.utc_now()
    ranked_games = repository.list_ranked_games_for_leg(bot.conn, week_id, parlay_id, now)
    embed = discord.Embed(title="🏈 Top 25 Games", description=_format_ranked_list(ranked_games))
    return embed, RankedGamePickerView(bot, parlay_id, week_id, ranked_games)


class RankedGamePickerView(discord.ui.View):
    def __init__(
        self, bot, parlay_id: int, week_id: int, ranked_games: list[tuple[int, int | None, int | None, object]]
    ):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.bot = bot
        self.parlay_id = parlay_id
        self.week_id = week_id
        self.ranked_games = ranked_games
        self._build()

    def _build(self):
        self.clear_items()
        options = [
            discord.SelectOption(
                label=_matchup_label(home_rank, away_rank, game)[:100],
                value=str(game["id"]),
                description=_kickoff_label(game["start_time_utc"]),
            )
            for _sort_rank, home_rank, away_rank, game in self.ranked_games[:PAGE_SIZE]
        ]
        select = discord.ui.Select(
            placeholder="Choose a ranked game..." if options else "No ranked games available",
            options=options or [discord.SelectOption(label="No ranked games available", value="none")],
            disabled=not options,
        )
        select.callback = self._on_select
        self.add_item(select)

        show_all_button = discord.ui.Button(label="Show All Games", style=discord.ButtonStyle.secondary)
        show_all_button.callback = self._on_show_all
        self.add_item(show_all_button)

        back_button = discord.ui.Button(label="Back", style=discord.ButtonStyle.danger)
        back_button.callback = self._on_back
        self.add_item(back_button)

    async def _on_select(self, interaction: discord.Interaction):
        game_id = int(interaction.data["values"][0])
        game = repository.get_game(self.bot.conn, game_id)
        embed, view = _market_screen(self.bot, self.parlay_id, self.week_id, game)
        await interaction.response.edit_message(embed=embed, view=view)

    async def _on_show_all(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Add a leg", description="Pick a game from the dropdown below.")
        view = GamePickerView(self.bot, self.parlay_id, self.week_id, page=0)
        await interaction.response.edit_message(embed=embed, view=view)

    async def _on_back(self, interaction: discord.Interaction):
        embed, view = render_panel(self.bot, self.parlay_id)
        await interaction.response.edit_message(embed=embed, view=view)


class GamePickerView(discord.ui.View):
    def __init__(self, bot, parlay_id: int, week_id: int, page: int = 0):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.bot = bot
        self.parlay_id = parlay_id
        self.week_id = week_id
        self.page = page
        self._build()

    def _build(self):
        self.clear_items()
        now = timeutils.utc_now()
        games, total = repository.list_available_games_for_leg(
            self.bot.conn, self.week_id, self.parlay_id, now, self.page, PAGE_SIZE
        )

        options = [
            discord.SelectOption(
                label=f"{g['away_team']} vs {g['home_team']}"[:100],
                value=str(g["id"]),
                description=_kickoff_label(g["start_time_utc"]),
            )
            for g in games
        ]
        select = discord.ui.Select(
            placeholder="Choose a game..." if options else "No games available",
            options=options or [discord.SelectOption(label="No games available", value="none")],
            disabled=not options,
        )
        select.callback = self._on_select
        self.add_item(select)

        if self.page > 0:
            prev_button = discord.ui.Button(label="◀ Prev", style=discord.ButtonStyle.secondary)
            prev_button.callback = self._on_prev
            self.add_item(prev_button)
        if (self.page + 1) * PAGE_SIZE < total:
            next_button = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.secondary)
            next_button.callback = self._on_next
            self.add_item(next_button)

        back_button = discord.ui.Button(label="Back", style=discord.ButtonStyle.danger)
        back_button.callback = self._on_back
        self.add_item(back_button)

    async def _on_select(self, interaction: discord.Interaction):
        game_id = int(interaction.data["values"][0])
        game = repository.get_game(self.bot.conn, game_id)
        embed, view = _market_screen(self.bot, self.parlay_id, self.week_id, game)
        await interaction.response.edit_message(embed=embed, view=view)

    async def _on_prev(self, interaction: discord.Interaction):
        self.page -= 1
        self._build()
        await interaction.response.edit_message(view=self)

    async def _on_next(self, interaction: discord.Interaction):
        self.page += 1
        self._build()
        await interaction.response.edit_message(view=self)

    async def _on_back(self, interaction: discord.Interaction):
        embed, view = _ranked_screen(self.bot, self.parlay_id, self.week_id)
        await interaction.response.edit_message(embed=embed, view=view)


def _market_screen(bot, parlay_id: int, week_id: int, game) -> tuple[discord.Embed, "MarketPickerView"]:
    embed = discord.Embed(
        title=f"{game['away_team']} vs {game['home_team']}", description="Pick a bet type."
    )
    logo_url = repository.get_team_logo(bot.conn, game["home_team"])
    if logo_url:
        embed.set_thumbnail(url=logo_url)
    snapshot = repository.get_latest_odds_snapshot(bot.conn, game["id"])

    for market, label in (("spread", "Spread"), ("moneyline", "Moneyline"), ("total", "Total")):
        lines = formatting.format_market_lines(game, snapshot, market)
        if lines:
            embed.add_field(name=label, value=lines, inline=True)
    if not embed.fields:
        embed.add_field(name="Lines", value="No odds cached for this game yet.", inline=False)

    return embed, MarketPickerView(bot, parlay_id, week_id, game, snapshot)


class MarketPickerView(discord.ui.View):
    def __init__(self, bot, parlay_id: int, week_id: int, game, snapshot):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.bot = bot
        self.parlay_id = parlay_id
        self.week_id = week_id
        self.game = game
        self.snapshot = snapshot
        self._build()

    def _build(self):
        self.clear_items()
        markets = (
            ("spread", "Spread", self.snapshot and self.snapshot["spread_home"] is not None),
            ("moneyline", "Moneyline", self.snapshot and self.snapshot["moneyline_home"] is not None),
            ("total", "Total", self.snapshot and self.snapshot["total_points"] is not None),
        )
        for market, label, available in markets:
            button = discord.ui.Button(
                label=label, style=discord.ButtonStyle.primary, disabled=not available
            )
            button.callback = self._make_callback(market)
            self.add_item(button)

        back_button = discord.ui.Button(label="Back", style=discord.ButtonStyle.danger)
        back_button.callback = self._on_back
        self.add_item(back_button)

    def _make_callback(self, market: str):
        async def callback(interaction: discord.Interaction):
            embed, view = _selection_screen(self.bot, self.parlay_id, self.week_id, self.game, self.snapshot, market)
            await interaction.response.edit_message(embed=embed, view=view)

        return callback

    async def _on_back(self, interaction: discord.Interaction):
        embed, view = _ranked_screen(self.bot, self.parlay_id, self.week_id)
        await interaction.response.edit_message(embed=embed, view=view)


def _selection_screen(
    bot, parlay_id: int, week_id: int, game, snapshot, market: str
) -> tuple[discord.Embed, "SelectionPickerView"]:
    embed = discord.Embed(
        title=f"{game['away_team']} vs {game['home_team']}",
        description=f"Pick your {market} selection.",
    )
    logo_url = repository.get_team_logo(bot.conn, game["home_team"])
    if logo_url:
        embed.set_thumbnail(url=logo_url)
    return embed, SelectionPickerView(bot, parlay_id, week_id, game, snapshot, market)


class SelectionPickerView(discord.ui.View):
    def __init__(self, bot, parlay_id: int, week_id: int, game, snapshot, market: str):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.bot = bot
        self.parlay_id = parlay_id
        self.week_id = week_id
        self.game = game
        self.snapshot = snapshot
        self.market = market
        self._build()

    def _build(self):
        self.clear_items()
        for selection in selections.selection_options(self.market):
            line_value, price = selections.resolve_selection(self.snapshot, self.market, selection)
            if price is None:
                continue
            label = formatting.format_selection_button_label(self.game, self.market, selection, line_value, price)
            button = discord.ui.Button(label=label[:80], style=discord.ButtonStyle.success)
            button.callback = self._make_callback(selection, line_value, price)
            self.add_item(button)

        back_button = discord.ui.Button(label="Back", style=discord.ButtonStyle.danger)
        back_button.callback = self._on_back
        self.add_item(back_button)

    def _make_callback(self, selection: str, line_value, price: int):
        async def callback(interaction: discord.Interaction):
            repository.add_leg(
                self.bot.conn, self.parlay_id, self.game["id"], self.snapshot["id"],
                self.market, selection, line_value, price,
            )
            embed, view = render_panel(self.bot, self.parlay_id)

            team = {"home": self.game["home_team"], "away": self.game["away_team"]}.get(selection)
            zinger = zingers.get_zinger(team, interaction.user.name)
            if zinger:
                embed.add_field(name="🔥 Real Talk", value=zinger, inline=False)

            await interaction.response.edit_message(embed=embed, view=view)

        return callback

    async def _on_back(self, interaction: discord.Interaction):
        embed, view = _market_screen(self.bot, self.parlay_id, self.week_id, self.game)
        await interaction.response.edit_message(embed=embed, view=view)


class RemoveLegView(discord.ui.View):
    def __init__(self, bot, parlay_id: int):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.bot = bot
        self.parlay_id = parlay_id
        self._build()

    def _build(self):
        self.clear_items()
        legs = repository.list_legs_with_games(self.bot.conn, self.parlay_id)
        select = discord.ui.Select(
            placeholder="Choose a leg to remove...",
            options=[
                discord.SelectOption(label=formatting.format_leg(leg)[:100], value=str(leg["leg_number"]))
                for leg in legs
            ],
        )
        select.callback = self._on_select
        self.add_item(select)

        back_button = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary)
        back_button.callback = self._on_back
        self.add_item(back_button)

    async def _on_select(self, interaction: discord.Interaction):
        leg_number = int(interaction.data["values"][0])
        repository.remove_leg(self.bot.conn, self.parlay_id, leg_number)
        embed, view = render_panel(self.bot, self.parlay_id)
        await interaction.response.edit_message(embed=embed, view=view)

    async def _on_back(self, interaction: discord.Interaction):
        embed, view = render_panel(self.bot, self.parlay_id)
        await interaction.response.edit_message(embed=embed, view=view)


def _wager_screen(bot, parlay_id: int, participant) -> tuple[discord.Embed, "WagerView"]:
    legs = repository.list_legs_with_games(bot.conn, parlay_id)
    leg_summary = "\n".join(formatting.format_leg(leg) for leg in legs)
    embed = discord.Embed(
        title="Choose your wager",
        description=f"{leg_summary}\n\nYour balance: ${participant['current_balance']:.2f}",
    )
    return embed, WagerView(bot, parlay_id, participant["id"], participant["current_balance"])


class WagerView(discord.ui.View):
    def __init__(self, bot, parlay_id: int, participant_id: int, balance: float):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.bot = bot
        self.parlay_id = parlay_id
        self.participant_id = participant_id
        self.balance = balance
        self._build()

    def _build(self):
        self.clear_items()
        legs = repository.list_legs(self.bot.conn, self.parlay_id)
        prices = [leg["price_american"] for leg in legs]

        for label, amount in payout.wager_presets(self.balance):
            potential = payout.potential_payout(amount, prices)
            button = discord.ui.Button(
                label=f"{label} → ${potential:.2f}", style=discord.ButtonStyle.success
            )
            button.callback = self._make_callback(amount)
            self.add_item(button)

        if self.balance > 0:
            custom_button = discord.ui.Button(label="Custom amount", style=discord.ButtonStyle.primary)
            custom_button.callback = self._on_custom
            self.add_item(custom_button)

        back_button = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary)
        back_button.callback = self._on_back
        self.add_item(back_button)

    def _make_callback(self, amount: float):
        async def callback(interaction: discord.Interaction):
            await self.confirm(interaction, amount)

        return callback

    async def _on_custom(self, interaction: discord.Interaction):
        await interaction.response.send_modal(WagerModal(self))

    async def confirm(self, interaction: discord.Interaction, amount: float):
        legs = repository.list_legs_with_games(self.bot.conn, self.parlay_id)
        prices = [leg["price_american"] for leg in legs]
        potential = payout.potential_payout(amount, prices)
        leg_summary = "\n".join(formatting.format_leg(leg) for leg in legs)
        embed = discord.Embed(
            title="Confirm your parlay",
            description=(
                f"{leg_summary}\n\nWager: ${amount:.2f}\nPotential payout: ${potential:.2f}\n"
                f"Balance after: ${self.balance - amount:.2f}"
            ),
        )
        view = ConfirmSubmitView(self.bot, self.parlay_id, self.participant_id, amount, potential, interaction.user.id)
        await interaction.response.edit_message(embed=embed, view=view)

    async def _on_back(self, interaction: discord.Interaction):
        embed, view = render_panel(self.bot, self.parlay_id)
        await interaction.response.edit_message(embed=embed, view=view)


class WagerModal(discord.ui.Modal, title="Custom wager amount"):
    amount = discord.ui.TextInput(label="Dollar amount", placeholder="e.g. 150")

    def __init__(self, wager_view: WagerView):
        super().__init__()
        self.wager_view = wager_view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = round(float(self.amount.value), 2)
        except ValueError:
            await interaction.response.send_message("Enter a valid dollar amount.", ephemeral=True)
            return
        if amount <= 0 or amount > self.wager_view.balance:
            await interaction.response.send_message(
                f"Enter an amount between $0.01 and ${self.wager_view.balance:.2f}.", ephemeral=True
            )
            return
        await self.wager_view.confirm(interaction, amount)


class ConfirmSubmitView(discord.ui.View):
    def __init__(self, bot, parlay_id: int, participant_id: int, wager: float, potential: float, owner_id: int):
        super().__init__(timeout=120)
        self.bot = bot
        self.parlay_id = parlay_id
        self.participant_id = participant_id
        self.wager = wager
        self.potential = potential
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This isn't your confirmation.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button):
        ok = repository.submit_parlay(self.bot.conn, self.parlay_id, self.participant_id, self.wager, self.potential)
        if not ok:
            embed = discord.Embed(
                title="Submit failed",
                description="Your balance changed since you started this - try again.",
            )
            await interaction.response.edit_message(embed=embed, view=None)
            return
        embed = discord.Embed(
            title="Parlay submitted! 🎉",
            description=f"Wager ${self.wager:.2f}, potential payout ${self.potential:.2f}.",
        )
        await interaction.response.edit_message(embed=embed, view=None)
        await status_panel.refresh(self.bot)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button):
        embed, view = render_panel(self.bot, self.parlay_id)
        await interaction.response.edit_message(embed=embed, view=view)
