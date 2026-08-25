import logging

import discord
import httpx
from discord import app_commands
from discord.ext import commands

from bot.parlays import flair_icons, repository, zingers

logger = logging.getLogger("degen_bot.flair")

AUTOCOMPLETE_LIMIT = 25
NO_ROLE_PERMS_MESSAGE = (
    "I don't have permission to manage roles here - ask an admin to grant me "
    "Manage Roles, and make sure my role sits above the team flair roles."
)


async def team_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    bot = interaction.client
    schools = repository.search_team_schools(bot.conn, current, limit=AUTOCOMPLETE_LIMIT)
    return [app_commands.Choice(name=school, value=school) for school in schools]


def _parse_color(hex_color: str | None) -> discord.Color:
    if not hex_color:
        return discord.Color.default()
    try:
        return discord.Color(int(hex_color.lstrip("#"), 16))
    except ValueError:
        return discord.Color.default()


async def _fetch_icon_bytes(logo_url: str | None) -> bytes | None:
    if not logo_url:
        return None
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(logo_url, timeout=10)
            response.raise_for_status()
            return response.content
    except httpx.HTTPError:
        logger.warning("Failed to download team logo from %s for a flair role icon", logo_url)
        return None


async def _get_or_create_flair_role(bot, guild: discord.Guild, school: str) -> discord.Role:
    role_id = repository.get_flair_role_id(bot.conn, school)
    if role_id is not None:
        role = guild.get_role(role_id)
        if role is not None:
            return role
        # role was deleted on Discord's side since we last recorded it - fall through
        # and recreate it below

    team = repository.get_team(bot.conn, school)
    color = _parse_color(team["color"] if team else None)
    # a small, pre-cropped Reddit flair icon reads far better as a round role
    # icon than a full team logo does - fall back to the CFBD logo for the
    # handful of teams (recent FBS transitions) not on that site yet
    icon_url = flair_icons.get_flair_icon_url(school) or (team["logo_url"] if team else None)
    icon_bytes = await _fetch_icon_bytes(icon_url)

    try:
        role = await guild.create_role(
            name=school,
            color=color,
            display_icon=icon_bytes if icon_bytes is not None else discord.utils.MISSING,
            hoist=True,
            mentionable=False,
            reason="Team flair role",
        )
    except discord.HTTPException:
        # icon upload rejected (too large, wrong format, or the server isn't boosted
        # enough for role icons) - fall back to a plain colored role rather than
        # failing the whole command over cosmetics
        role = await guild.create_role(
            name=school,
            color=color,
            hoist=True,
            mentionable=False,
            reason="Team flair role",
        )

    repository.set_flair_role_id(bot.conn, school, role.id)
    return role


async def handle_set_flair(interaction: discord.Interaction, school: str) -> None:
    bot = interaction.client
    await interaction.response.defer(ephemeral=True, thinking=True)

    # Everything below runs after the interaction has already been deferred, so any
    # exception that escapes uncaught leaves the user staring at "thinking..."
    # forever - discord.py's default View/Modal error handler only logs, it doesn't
    # reply. Catch broadly and always resolve the interaction one way or another.
    try:
        await _do_set_flair(interaction, school)
    except Exception:
        logger.exception("Failed to set flair for %s -> %s", interaction.user, school)
        await interaction.followup.send(
            "Something went wrong setting that flair - try again in a bit.", ephemeral=True
        )


async def _do_set_flair(interaction: discord.Interaction, school: str) -> None:
    bot = interaction.client

    if not repository.team_exists(bot.conn, school):
        await interaction.followup.send(
            f"Don't recognize '{school}' - pick a team from the list "
            "(run /admin sync-teams first if the list looks empty).",
            ephemeral=True,
        )
        return

    guild = interaction.guild
    member = interaction.user

    try:
        role = await _get_or_create_flair_role(bot, guild, school)
    except discord.Forbidden:
        await interaction.followup.send(NO_ROLE_PERMS_MESSAGE, ephemeral=True)
        return

    other_flair_role_ids = set(repository.list_flair_role_ids(bot.conn)) - {role.id}
    roles_to_remove = [r for r in member.roles if r.id in other_flair_role_ids]
    already_had_role = role in member.roles
    changed = bool(roles_to_remove) or not already_had_role

    try:
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove, reason="Switching team flair")
        if not already_had_role:
            await member.add_roles(role, reason="Set team flair")
    except discord.Forbidden:
        await interaction.followup.send(NO_ROLE_PERMS_MESSAGE, ephemeral=True)
        return

    if changed:
        await interaction.followup.send(f"You're now flaired for the {school}.", ephemeral=True)
        await bot.announce(zingers.get_flair_reaction(school, interaction.user.name))
    else:
        await interaction.followup.send(f"You're already flaired for the {school}.", ephemeral=True)


async def handle_clear_flair(interaction: discord.Interaction) -> None:
    bot = interaction.client
    await interaction.response.defer(ephemeral=True, thinking=True)

    member = interaction.user
    flair_role_ids = set(repository.list_flair_role_ids(bot.conn))
    roles_to_remove = [r for r in member.roles if r.id in flair_role_ids]

    if not roles_to_remove:
        await interaction.followup.send("You don't have a team flair set.", ephemeral=True)
        return

    try:
        await member.remove_roles(*roles_to_remove, reason="Cleared team flair")
    except discord.Forbidden:
        await interaction.followup.send(NO_ROLE_PERMS_MESSAGE, ephemeral=True)
        return

    await interaction.followup.send("Team flair cleared.", ephemeral=True)


class FlairErrorView(discord.ui.View):
    """discord.py's default View error handler only logs an exception - it never
    replies, which leaves the user staring at "thinking..." forever if something
    throws inside a callback after a defer. Every view below inherits this so a
    failure always surfaces as a message instead of a silent hang."""

    async def on_error(self, interaction: discord.Interaction, error: Exception, item) -> None:
        logger.exception("Error in flair view item %r", item, exc_info=error)
        message = "Something went wrong - try again in a bit."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass  # interaction webhook already expired/invalid - nothing more we can do


class FlairTeamSelect(discord.ui.Select):
    """The second step: teams in the conference picked from FlairConferenceSelect.
    A conference tops out well under Discord's 25-option select cap, and Discord's
    client shows an inline search box on any select with several options, so this
    already gets the "scroll or type to filter" experience without any extra work."""

    def __init__(self, schools: list[str]):
        options = [discord.SelectOption(label=school) for school in schools[:AUTOCOMPLETE_LIMIT]]
        super().__init__(placeholder="Pick your team", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        await handle_set_flair(interaction, self.values[0])


class FlairTeamView(FlairErrorView):
    def __init__(self, schools: list[str]):
        super().__init__(timeout=120)
        self.add_item(FlairTeamSelect(schools))


class FlairConferenceSelect(discord.ui.Select):
    def __init__(self, conferences: list[str]):
        options = [discord.SelectOption(label=conference) for conference in conferences[:AUTOCOMPLETE_LIMIT]]
        super().__init__(placeholder="Pick your conference", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        bot = interaction.client
        conference = self.values[0]
        schools = repository.list_teams_in_conference(bot.conn, conference)
        if not schools:
            await interaction.response.send_message(
                f"No teams found for '{conference}' - run /admin sync-teams and try again.",
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(
            content=f"**{conference}** - pick your team:", view=FlairTeamView(schools)
        )


class FlairConferenceView(FlairErrorView):
    """Opened by the panel's Set Flair button - a button click can't carry the
    autocomplete /flair set gets from Discord, so this browses by conference
    instead: pick a conference, then pick (or type-to-filter) a team from it."""

    def __init__(self, conferences: list[str]):
        super().__init__(timeout=120)
        self.add_item(FlairConferenceSelect(conferences))


async def handle_open_flair_picker(interaction: discord.Interaction) -> None:
    bot = interaction.client
    conferences = repository.list_conferences(bot.conn)
    if not conferences:
        await interaction.response.send_message(
            "No teams cached yet - run /admin sync-teams first.", ephemeral=True
        )
        return
    await interaction.response.send_message(
        "Pick your conference:", view=FlairConferenceView(conferences), ephemeral=True
    )


class FlairCog(commands.GroupCog, name="flair"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()

    @app_commands.command(
        name="set", description="Show your support for a team with a colored, iconed role"
    )
    @app_commands.describe(team="Team name, e.g. 'Ohio State' or 'Purdue'")
    @app_commands.autocomplete(team=team_autocomplete)
    async def set_flair(self, interaction: discord.Interaction, team: str):
        await handle_set_flair(interaction, team)

    @app_commands.command(name="clear", description="Remove your team flair role")
    async def clear_flair(self, interaction: discord.Interaction):
        await handle_clear_flair(interaction)


async def setup(bot: commands.Bot):
    await bot.add_cog(FlairCog(bot))
