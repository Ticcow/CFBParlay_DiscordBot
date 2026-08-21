import asyncio
import logging
from datetime import timedelta

import discord

from bot.config import settings
from bot.parlays import formatting, repository

logger = logging.getLogger("degen_bot.panel")

PANEL_EMBED_TITLE = "🎰 Degen Bot — Week Status"
MAX_BET_FIELDS = 20

HOW_TO_PLAY = (
    "🎲 **Opt In** — join the week with a $1,000 bankroll\n"
    "🏈 **Start Parlay** — pick 3-6 games and lock in a wager\n"
    "🏆 Highest balance when the week's games finish wins\n"
    "🎽 **/flair set** — get a colored, iconed role for your team"
)

# How far back to look for a leftover panel (e.g. posted before a bot restart,
# which wipes the in-memory _panels tracking but leaves the message sitting in
# the channel). Recent history only - not a full-channel scan.
_STALE_PANEL_SCAN_LIMIT = 50

# cleanup_channel() deletes anything in the panel channel older than this that
# isn't the current panel - the channel is meant to be nothing but the panel.
CLEANUP_AGE = timedelta(minutes=5)
_CLEANUP_SCAN_LIMIT = 200

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
        # sync_week/sync_teams/refresh_panel all work with no week open (sync_week
        # is how a week gets created in the first place) - only refresh_odds needs
        # one to already exist, same as the /admin refresh-odds command does.
        self.refresh_odds_button.disabled = not week_is_open

    @discord.ui.button(label="🎲 Opt In", style=discord.ButtonStyle.success, custom_id="degen_bot:panel:optin", row=0)
    async def optin_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        from bot.commands import bankroll

        await bankroll.handle_optin(interaction)

    @discord.ui.button(
        label="🏈 Start Parlay", style=discord.ButtonStyle.primary, custom_id="degen_bot:panel:start_parlay", row=0
    )
    async def start_parlay_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        from bot.commands import parlay

        await parlay.handle_start_parlay(interaction)

    @discord.ui.button(
        label="🎽 Set Flair", style=discord.ButtonStyle.secondary, custom_id="degen_bot:panel:set_flair", row=0
    )
    async def set_flair_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        from bot.commands.flair import FlairSearchModal

        await interaction.response.send_modal(FlairSearchModal())

    @discord.ui.button(
        label="🔄 Sync Week", style=discord.ButtonStyle.secondary, custom_id="degen_bot:panel:sync_week", row=1
    )
    async def sync_week_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        from bot.commands import admin

        await admin.handle_sync_week(interaction)

    @discord.ui.button(
        label="🖼️ Sync Teams", style=discord.ButtonStyle.secondary, custom_id="degen_bot:panel:sync_teams", row=1
    )
    async def sync_teams_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        from bot.commands import admin

        await admin.handle_sync_teams(interaction)

    @discord.ui.button(
        label="💰 Refresh Odds", style=discord.ButtonStyle.secondary, custom_id="degen_bot:panel:refresh_odds", row=1
    )
    async def refresh_odds_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        from bot.commands import admin

        await admin.handle_refresh_odds(interaction)

    @discord.ui.button(
        label="🔃 Refresh Panel", style=discord.ButtonStyle.secondary, custom_id="degen_bot:panel:refresh_panel", row=1
    )
    async def refresh_panel_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        from bot.commands import admin

        await admin.handle_refresh_panel(interaction)


def _build_embed(bot, week) -> discord.Embed:
    embed = discord.Embed(title=PANEL_EMBED_TITLE, color=discord.Color.gold())
    embed.add_field(name="How to Play", value=HOW_TO_PLAY, inline=False)

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
    if not submitted:
        embed.add_field(name="Bets", value="No parlays submitted yet.", inline=False)
    else:
        for parlay in submitted[:MAX_BET_FIELDS]:
            legs = repository.list_legs_with_games(bot.conn, parlay["id"])
            leg_text = "\n".join(formatting.format_leg(leg) for leg in legs)
            wager = f"${parlay['wager_dollars']:.2f}" if parlay["wager_dollars"] is not None else "-"

            if parlay["status"] == "graded":
                payout_text = f"${parlay['actual_payout_dollars']:.2f} payout"
                status_label = parlay["result"].upper()
            else:
                potential = (
                    f"${parlay['potential_payout_dollars']:.2f}"
                    if parlay["potential_payout_dollars"] is not None
                    else "-"
                )
                payout_text = f"{potential} potential"
                status_label = parlay["status"]

            embed.add_field(
                name=f"<@{parlay['user_id']}> — {wager} wager → {payout_text} [{status_label}]",
                value=leg_text[:1024],
                inline=False,
            )
        if len(submitted) > MAX_BET_FIELDS:
            embed.add_field(
                name="...", value=f"+{len(submitted) - MAX_BET_FIELDS} more parlay(s) not shown", inline=False
            )

    embed.set_footer(text="More: /balance, /parlays, /leaderboard, /mystats, /history")
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


async def cleanup_channel(bot) -> int:
    """Deletes anything in the panel channel older than CLEANUP_AGE that isn't
    the current panel message - the channel is meant to show nothing else.
    Requires the bot to have Manage Messages there (Send Messages alone only
    lets a bot delete its own messages, not other members'); if that's missing,
    logs once and stops rather than retrying every message. Returns how many
    messages were removed."""
    if not settings.admin_log_channel_id:
        return 0
    channel_id = settings.admin_log_channel_id

    try:
        channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
    except discord.HTTPException:
        logger.warning("Failed to fetch panel channel %s", channel_id)
        return 0

    current_panel = _panels.get(channel_id)
    cutoff = discord.utils.utcnow() - CLEANUP_AGE
    removed = 0
    try:
        async for message in channel.history(limit=_CLEANUP_SCAN_LIMIT):
            if current_panel is not None and message.id == current_panel.id:
                continue
            if message.created_at > cutoff:
                continue  # give people a few minutes to actually read it
            try:
                await message.delete()
                removed += 1
            except discord.Forbidden:
                logger.warning(
                    "Missing Manage Messages permission in channel %s - can't clean it up. "
                    "Grant it in Server Settings > Roles, or as a channel-specific override.",
                    channel_id,
                )
                return removed
            except discord.HTTPException:
                pass
    except discord.HTTPException:
        logger.warning("Failed to scan channel %s for cleanup", channel_id)
    return removed
