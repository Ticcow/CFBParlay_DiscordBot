import discord


async def resolve_username(bot, user_id: int) -> str:
    """The real Discord username (not nickname/display name - matches how
    zingers address people) for a user_id. Embed field *values* and plain
    message content resolve a raw <@id> mention into a clickable name on
    their own, but embed field *names* don't - Discord just shows the
    literal "<@123...>" text there, so callers building a field name need
    the plain username up front instead.

    Checked against the gateway cache first, with a fetch as a fallback so
    it still works for a member the cache hasn't seen (no Members intent is
    enabled). Falls back to the bare id as a string if the user can no
    longer be resolved at all (e.g. they deleted their Discord account)."""
    user = bot.get_user(user_id)
    if user is None:
        try:
            user = await bot.fetch_user(user_id)
        except discord.HTTPException:
            return str(user_id)
    return user.name
