import logging

import discord
from discord.ext import commands

from bot import db as db_module
from bot.config import settings
from bot.integrations.cfbd_client import CfbdClient
from bot.integrations.odds_client import OddsClient
from bot.parlays import repository
from bot.scheduler import jobs as scheduler_jobs

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("degen_bot")

EXTENSIONS = (
    "bot.commands.admin",
    "bot.commands.board",
    "bot.commands.bankroll",
    "bot.commands.parlay",
    "bot.commands.leaderboard",
)


class DegenBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        # No text-command prefix is actually usable here (Message Content Intent is
        # deliberately left off - see plan), this only exists to satisfy commands.Bot's
        # constructor. Every real command is a "/" slash command, which is unaffected
        # by this value.
        super().__init__(command_prefix="/", intents=intents)
        self.conn = db_module.connect(settings.database_path)
        db_module.run_migrations(self.conn)

        def log_usage(service: str, endpoint: str, credits_used: int = 1) -> None:
            repository.log_api_usage(self.conn, service, endpoint, credits_used)

        self.cfbd = CfbdClient(settings.cfbd_api_key, log_usage=log_usage)
        self.odds = OddsClient(settings.odds_api_key, log_usage=log_usage)
        self.scheduler = None
        self._scheduler_started = False

    async def setup_hook(self):
        for extension in EXTENSIONS:
            await self.load_extension(extension)

        if settings.dev_guild_id:
            guild = discord.Object(id=settings.dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info("Synced commands to dev guild %s", settings.dev_guild_id)
        else:
            await self.tree.sync()
            logger.info("Synced commands globally")

    async def on_ready(self):
        logger.info("Logged in as %s (id=%s)", self.user, self.user.id)
        # on_ready can re-fire after a reconnect; only register jobs once per process,
        # and only once the guild/channel cache is actually populated.
        if not self._scheduler_started:
            self.scheduler = scheduler_jobs.register_jobs(self)
            self._scheduler_started = True
            logger.info("Scheduler started")

    async def announce(self, message: str) -> None:
        if not settings.admin_log_channel_id:
            logger.warning("ADMIN_LOG_CHANNEL_ID not configured; dropped announcement: %s", message)
            return
        channel = self.get_channel(settings.admin_log_channel_id)
        if channel is None:
            channel = await self.fetch_channel(settings.admin_log_channel_id)
        await channel.send(message)


async def on_app_command_error(
    interaction: discord.Interaction, error: discord.app_commands.AppCommandError
):
    logger.exception("Slash command error", exc_info=error)
    message = "Something went wrong running that command."
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


def main():
    bot = DegenBot()
    bot.tree.on_error = on_app_command_error
    bot.run(settings.discord_bot_token)


if __name__ == "__main__":
    main()
