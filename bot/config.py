from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    discord_bot_token: str
    cfbd_api_key: str
    odds_api_key: str = ""
    database_path: str = "degen_bot.db"
    admin_log_channel_id: int | None = None
    dev_guild_id: int | None = None

    @field_validator("admin_log_channel_id", "dev_guild_id", mode="before")
    @classmethod
    def _blank_env_value_means_unset(cls, value):
        # an unfilled-in .env line (e.g. "DEV_GUILD_ID=") arrives as "", which
        # int-parses as invalid rather than as "not provided" - treat it as None
        return None if value == "" else value


settings = Settings()
