import asyncio
import logging

import discord

from bot.config import settings
from bot.parlays import formatting, repository

logger = logging.getLogger("degen_bot.panel")

PANEL_EMBED_TITLE = "🎰 Degen Bot — Week Status"
MAX_BET_FIELDS = 20

# How far back to look for a leftover panel (e.g. posted before a bot restart,
# which wipes the in-memory _panels tracking but leaves the message sitting in
# the channel). Recent history only - not a full-channel scan.
_STALE_PANEL_SCAN_LIMIT = 50

_panels: dict[int, discord.Message] = {}

# refresh() reads-then-writes _panels[channel_id]; two near-simultaneous callers
# (e.g. a submit and a scheduled job landing at the same moment) could otherwise
# both post a new panel and only one gets tracked, leaving the other orphaned.
_locks: dict[int, asyncio.Lock] = {}


def _lock_for(channel_id: int) -> asyncio.Lock:
    return _locks.setdefault(channel_id, asyncio.Lock())


class PanelActionsView(discord.ui.View):
    """Stateless and registered as a persistent view (see main.py's setup_hook)
    so these buttons keep working on old panel messages even across a bot
    restart, not just until the next refresh happens to repost a fresh one.
    Each button's own logic lives in bankroll.py/parlay.py, shared verbatim
    with the equivalent slash command - imported lazily here to avoid a
    circular import, since those modules import this one for status_panel.refresh()."""

    def __init__(self, *, week_is_open: bool = True):
        super().__init__(timeout=None)
        self.optin_button.disabled = not week_is_open
        self.start_parlay_button.disabled = not week_is_open

    @discord.ui.button(label="🎲 Opt In", style=discord.ButtonStyle.success, custom_id="degen_bot:panel:optin")
    async def optin_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        from bot.commands import bankroll

        await bankroll.handle_optin(interaction)

    @discord.ui.button(
        label="🏈 Start Parlay", style=discord.ButtonStyle.primary, custom_id="degen_bot:panel:start_parlay"
    )
    async def start_parlay_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        from bot.commands import parlay

        await parlay.handle_start_parlay(interaction)


def _build_embed(bot, week) -> discord.Embed:
    embed = discord.Embed(title=PANEL_EMBED_TITLE, color=discord.Color.gold())
    if week is None:
        embed.description = "No week is open yet."
        return embed

    embed.description = f"Week {week['week_number']} ({week['season_year']})"

    standings = repository.list_week_standings(bot.conn, week["id"])
    if standings:
        lines = []
        for i, row in enumerate(standings, start=1):
            crown = " 🏆" if row["is_weekly_winner"] else ""
            count = len(repository.list_parlays_for_user_week(bot.conn, row["user_id"], week["id"]))
            lines.append(
                f"{i}. <@{row['user_id']}> — ${row['current_balance']:.2f} ({count} parlay(s)){crown}"
            )
        embed.add_field(
            name=f"Standings ({len(standings)} opted in)", value="\n".join(lines)[:1024], inline=False
        )
    else:
        embed.add_field(name="Standings", value="Nobody has opted in yet - use /optin!", inline=False)

    submitted = repository.list_submitted_parlays_for_week(bot.conn, week["id"])
    visible = repository.week_is_visible(bot.conn, week["id"])
    if not submitted:
        embed.add_field(name="Bets", value="No parlays submitted yet.", inline=False)
    elif not visible:
        embed.add_field(
            name="Bets",
            value=f"{len(submitted)} parlay(s) submitted - picks stay hidden until the first game kicks off.",
            inline=False,
        )
    else:
        for parlay in submitted[:MAX_BET_FIELDS]:
            legs = repository.list_legs_with_games(bot.conn, parlay["id"])
            leg_text = "\n".join(formatting.format_leg(leg) for leg in legs)
            wager = f"${parlay['wager_dollars']:.2f}" if parlay["wager_dollars"] is not None else "-"
            embed.add_field(
                name=f"<@{parlay['user_id']}> — {wager} [{parlay['status']}]",
                value=leg_text[:1024],
                inline=False,
            )
        if len(submitted) > MAX_BET_FIELDS:
            embed.add_field(
                name="...", value=f"+{len(submitted) - MAX_BET_FIELDS} more parlay(s) not shown", inline=False
            )

    embed.set_footer(text="Buttons below to join in, or /optin, /parlay start, /leaderboard for season stats")
    return embed


async def _delete_stale_panels(channel) -> None:
    me = getattr(getattr(channel, "guild", None), "me", None)
    try:
        async for message in channel.history(limit=_STALE_PANEL_SCAN_LIMIT):
            if me is not None and message.author != me:
                continue
            if not message.embeds or message.embeds[0].title != PANEL_EMBED_TITLE:
                continue
            try:
                await message.delete()
            except discord.HTTPException:
                pass
    except discord.HTTPException:
        logger.warning("Failed to scan for stale week panels")


async def refresh(bot) -> None:
    """(Re)posts the week panel in the configured channel - deletes the previous
    copy and sends a new one so it stays the newest message instead of sinking
    under new chat as an edited-in-place message would. No-op if no channel is
    configured; swallows permission errors so a misconfigured channel can't
    take down whatever action triggered the refresh."""
    if not settings.admin_log_channel_id:
        return
    channel_id = settings.admin_log_channel_id

    async with _lock_for(channel_id):
        try:
            channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        except discord.HTTPException:
            logger.warning("Failed to fetch panel channel %s", channel_id)
            return

        week = repository.get_latest_week(bot.conn)
        embed = _build_embed(bot, week)
        view = PanelActionsView(week_is_open=week is not None)

        old_message = _panels.get(channel_id)
        if old_message is None:
            await _delete_stale_panels(channel)

        try:
            new_message = await channel.send(embed=embed, view=view)
        except discord.HTTPException:
            logger.warning("Failed to post week panel to channel %s", channel_id)
            return

        _panels[channel_id] = new_message
        if old_message is not None:
            try:
                await old_message.delete()
            except discord.NotFound:
                pass
